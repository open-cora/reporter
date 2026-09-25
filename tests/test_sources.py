"""Where documents come from, and what a frame off the wire says.

The decoder is checked against byte strings a real `bluesky` publisher
emitted, recorded by pointing a socket at one, not against a reading of
its source. The framing is the one thing here this project did not define,
so the assertion should be the wire and not an opinion about it.

The subscription itself is checked over a real loopback socket, because
the parts that could be wrong are the socket options rather than anything
a fake would exercise.
"""

import json
import re
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import msgpack
import pytest
import zmq

from reporter.sources import DecodeError, Delivery, decode, from_capture, from_subscription

CAPTURED = Path(__file__).parent / "documents.json"

PUBLISHED_START = b" start \x82\xa3uid\xa7abc-123\xa9plan_name\xa5count"
"""One frame, as `bluesky.callbacks.zmq.Publisher` put it on the socket.

Captured from a real publisher constructed with `serializer=msgpack.dumps`
and no prefix, which is why it opens with a space: the prefix is empty and
the separator is still there.
"""

PUBLISHED_STOP = b"beam stop \x82\xa9run_start\xa7abc-123\xabexit_status\xa7success"
"""The same, from a publisher carrying `prefix=b"beam"`."""


def published(name: str, document: dict[str, Any], prefix: bytes = b"") -> bytes:
    """A frame in the shape the two above are in."""
    return b" ".join([prefix, name.encode(), msgpack.dumps(document)])


def test_a_published_frame_decodes_to_its_name_and_document() -> None:
    assert decode(PUBLISHED_START) == ("start", {"uid": "abc-123", "plan_name": "count"})


def test_a_prefixed_frame_decodes_the_same_way() -> None:
    """The prefix selects a publisher at the socket. Past that it is not
    part of the document and nothing downstream sees it."""
    name, document = decode(PUBLISHED_STOP)

    assert name == "stop"
    assert document == {"run_start": "abc-123", "exit_status": "success"}


def test_the_frames_this_asserts_against_are_the_shape_it_builds() -> None:
    """Guard the helper. Every other test below builds its own frames, and
    a helper that drifted from the captured pair would make them all agree
    with each other and with nothing real."""
    assert published("start", {"uid": "abc-123", "plan_name": "count"}) == PUBLISHED_START
    assert (
        published("stop", {"run_start": "abc-123", "exit_status": "success"}, b"beam")
        == PUBLISHED_STOP
    )


def test_a_document_carrying_an_array_decodes_without_numpy() -> None:
    """What a real detector publishes. An encoder turns an array into a
    dict of its bytes, and a decoder without the matching hook gets the
    dict back rather than an array, which is fine: this reads scalars and
    skips the documents arrays arrive in. It is the reason numpy is not a
    dependency of a package that reads detector data."""
    frame = published("event", {"data": {"img": {b"nd": True, b"data": b"\x00\x01"}}, "seq_num": 1})

    _, document = decode(frame)

    assert document["seq_num"] == 1


def test_a_pickled_payload_is_refused_and_says_how_to_fix_it() -> None:
    """The default a publisher uses, and the one thing this will not read.
    Unpickling whatever reaches a port is remote code execution with a
    subscription in front of it."""
    import pickle

    frame = b" ".join([b"", b"start", pickle.dumps({"uid": "abc-123"})])

    with pytest.raises(DecodeError, match=re.escape("serializer=msgpack.dumps")):
        decode(frame)


def test_a_frame_that_is_not_three_parts_is_refused() -> None:
    with pytest.raises(DecodeError, match="prefix"):
        decode(b"nonsense")


def test_a_payload_that_is_not_a_document_is_refused() -> None:
    """A bare list decodes perfectly well. A document is a mapping,
    and anything else is a publisher this cannot read."""
    frame = b" ".join([b"", b"start", msgpack.dumps([1, 2, 3])])

    with pytest.raises(DecodeError, match="rather than a document"):
        decode(frame)


@pytest.fixture
def subscribed() -> Iterator[tuple[zmq.Socket[bytes], str]]:
    """A publishing socket, and the address a subscription reaches it at.

    The subscriber connects and the publisher binds, which is the reverse
    of a deployment, where both meet at a proxy. Either end may bind and
    the frames are identical; this way the test needs no proxy.
    """
    context = zmq.Context()
    publisher = context.socket(zmq.PUB)
    port = publisher.bind_to_random_port("tcp://127.0.0.1")
    try:
        yield publisher, f"tcp://127.0.0.1:{port}"
    finally:
        publisher.close()
        context.term()


PATIENCE_SECONDS = 5.0
"""How long a socket test waits before calling a document lost."""


def read_one(address: str, prefix: bytes = b"") -> tuple[list[Delivery], threading.Thread]:
    """Start reading one document from a subscription, on its own thread.

    Returned through a list because a thread cannot return one, and joined
    by the caller before the list is read.
    """
    received: list[Delivery] = []

    def read() -> None:
        documents = from_subscription(address, prefix=prefix, poll_milliseconds=50)
        try:
            received.append(next(documents))
        finally:
            documents.close()

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    return received, reader


def publish_until_read(
    publisher: "zmq.Socket[bytes]",
    reader: threading.Thread,
    *frames: bytes,
) -> None:
    """Send until somebody has read one, or give up and let the test say so.

    A publisher drops what it sends before a subscriber has finished
    attaching, and attaching is not finished when `connect` returns. So
    the frames go out repeatedly rather than once. A real engine has the
    same property and deals with it the same way, by being there first.
    """
    deadline = time.monotonic() + PATIENCE_SECONDS
    while reader.is_alive() and time.monotonic() < deadline:
        for frame in frames:
            publisher.send(frame)
        time.sleep(0.05)
    reader.join(0.5)


def test_a_published_document_arrives_through_a_subscription(
    subscribed: tuple[zmq.Socket[bytes], str],
) -> None:
    """The whole socket path, over a real one.

    Published repeatedly because a subscriber that has connected has not
    necessarily finished subscribing, and a publisher drops what it sends
    before anybody is listening. A real engine has the same property and
    solves it the same way: by being there first.
    """
    publisher, address = subscribed
    received, reader = read_one(address)

    publish_until_read(publisher, reader, published("start", {"uid": "abc-123"}))

    assert received == [("start", {"uid": "abc-123"})], (
        f"No document arrived through the subscription within {PATIENCE_SECONDS}s."
    )


def test_a_prefix_selects_one_publisher_and_leaves_the_others(
    subscribed: tuple[zmq.Socket[bytes], str],
) -> None:
    """What a facility running two engines past one proxy needs."""
    publisher, address = subscribed
    received, reader = read_one(address, prefix=b"ours")

    publish_until_read(
        publisher,
        reader,
        published("start", {"uid": "theirs"}, b"theirs"),
        published("start", {"uid": "ours"}, b"ours"),
    )

    assert received == [("start", {"uid": "ours"})]


def test_the_capture_flattens_into_one_stream_in_order() -> None:
    """A reporter sees one stream. The capture groups by scenario because it
    was written to compare them."""
    stream = list(from_capture(CAPTURED))

    assert stream
    assert all(isinstance(name, str) and isinstance(doc, dict) for name, doc in stream)
    assert stream[0][0] == "start"


def test_every_captured_document_survives_the_flattening() -> None:
    """Off-by-one here silently drops a run, and nothing downstream notices."""
    captured: dict[str, Any] = json.loads(CAPTURED.read_text(encoding="utf-8"))
    expected = sum(len(scenario["documents"]) for scenario in captured.values())

    assert len(list(from_capture(CAPTURED))) == expected


def test_the_msgpack_stub_describes_the_package_it_stands_in_for() -> None:
    """`typings/msgpack` is hand written and pyright takes it on trust.

    Both declarations are narrower than what msgpack infers on its own:
    `packb` is declared to return bytes where the package allows `None`,
    and that narrowing is what lets `decode` be checked at all. So it is
    worth one test that the package agrees.
    """
    packed = msgpack.packb({"uid": "abc-123"})

    assert isinstance(packed, bytes)
    assert msgpack.unpackb(packed) == {"uid": "abc-123"}
