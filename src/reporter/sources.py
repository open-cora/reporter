"""Where documents come from.

A source yields `(document name, document)` pairs in the order an engine
emitted them. `Session` and `Relay` take them one at a time and have no
opinion about the origin, so everything engine-shaped about getting hold
of a document stops here.

There are two. `from_capture` reads a file, which is how this gets tested
against a real keeper without a beamline. `from_subscription` reads a live
engine publishing over 0MQ, which is the one that makes this a reporter
rather than a replay tool.

Both are iterators, and the only difference that matters to a caller is
that the second one never ends.

## A third way in, which needs no code here

An engine in the same process hands documents over directly, because
`Relay.submit` already has the signature a subscription callback wants:

    RE.subscribe(relay.submit)

That is not a source and cannot be one. A source is pulled from and a
callback is pushed to, and when the engine is in this process there is
nothing to pull. See the README for the whole recipe.

## What is still undecided, and it is no longer liveness

Durability. 0MQ publish and subscribe is fire and forget: a subscriber
that is not running when a document goes out never learns it existed, and
there is no offset to come back to. That is at-most-once, which is what
`Relay` already says this reporter is, and closing it means a transport
that keeps a log rather than anything in this module.

So the subscription and the checkpoint turned out to be two decisions
after all, and only the second one is still open.
"""

import json
from collections.abc import Generator, Iterator
from contextlib import closing
from pathlib import Path
from typing import Any, Final, cast

import msgpack
import zmq

Delivery = tuple[str, dict[str, Any]]
"""One document, as the stream delivered it: its type name and its body."""

DEFAULT_POLL_MILLISECONDS: Final = 500
"""How long a subscription waits for a document before looking up.

It is not a timeout and nothing is lost by it: 0MQ queues what arrives
while nobody is asking. It is how often the loop reaches a point where an
interrupt can land, which is the difference between a process that stops
on Ctrl-C and one that has to be killed.
"""


class DecodeError(Exception):
    """A frame arrived that this cannot read as a published document."""


def from_capture(path: Path) -> Iterator[Delivery]:
    """Every document in a capture, flattened into one stream.

    The capture groups documents by scenario, because the spike that wrote
    it was comparing scenarios. A reporter sees one stream, so they are
    flattened into one here, which is also closer to what a subscription
    delivers.
    """
    captured: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    for scenario in captured.values():
        entries: list[dict[str, Any]] = scenario["documents"]
        for entry in entries:
            yield (str(entry["name"]), dict(entry["doc"]))


def from_subscription(
    address: str,
    *,
    prefix: bytes = b"",
    poll_milliseconds: int = DEFAULT_POLL_MILLISECONDS,
) -> Generator[Delivery]:
    """Documents from an engine publishing over 0MQ, until interrupted.

    `address` is a 0MQ endpoint such as `tcp://127.0.0.1:5568`, and it is
    normally the outbound side of a proxy rather than an engine directly,
    because publishing engines connect to a proxy rather than accept
    connections.

    `prefix` selects one publisher among several on the same proxy, and
    the default takes every one of them. A facility running two engines
    past one proxy is the case it exists for.

    Ends only by being interrupted or closed, so a caller that wants this
    to stop is the thing that has to stop it. A generator rather than a
    plain iterator for that reason: it holds a socket, and `close()` is
    how a caller on another thread gives it back.
    """
    context = zmq.Context()
    socket = context.socket(zmq.SUB)
    try:
        socket.connect(address)
        socket.setsockopt(zmq.SUBSCRIBE, prefix)
        with closing(socket):
            while True:
                if socket.poll(poll_milliseconds):
                    yield decode(socket.recv())
    finally:
        context.term()


def decode(frame: bytes) -> Delivery:
    """One published frame, as a document.

    The frame is a prefix, a document name and a payload, separated by
    single spaces, and the payload is the document:

        b"beam stop \\x82\\xa9run_start..."
          ^^^^ ^^^^  ^^^^^^^^^^^^^^^^^^^
          |    |     msgpack
          |    utf-8
          an empty prefix leaves the leading space, so there are always
          three parts

    The encoding is msgpack and only msgpack. A publisher that has not
    been told otherwise uses `pickle`, and a subscriber that went along
    with that would be running whatever code reached the port, which is
    not a thing to leave switched on at a facility. The refusal below
    names the fix, because the first person to meet it will be holding a
    working publisher and an error they did not cause.
    """
    try:
        _, name, payload = frame.split(b" ", 2)
    except ValueError as malformed:
        raise DecodeError(
            f"A frame of {len(frame)} bytes did not split into a prefix, a name and a "
            "payload, so it was not published by an engine this can read."
        ) from malformed

    try:
        document = msgpack.unpackb(payload)
    except Exception as unreadable:
        raise DecodeError(
            f"The payload of a {name.decode(errors='replace')!r} frame is not msgpack. "
            "A publisher encodes with pickle unless it is told not to, and this refuses "
            "to unpickle anything that arrives over a socket. Construct the publisher "
            "with serializer=msgpack.dumps."
        ) from unreadable

    if not isinstance(document, dict):
        raise DecodeError(
            f"A {name.decode(errors='replace')!r} frame carried {type(document).__name__} "
            "rather than a document."
        )

    # The keys are a claim rather than a check. msgpack hands back whatever
    # was encoded, and walking every key of every document to prove they are
    # strings would cost a scan per document to learn what the format
    # already guarantees.
    return (name.decode(), cast("dict[str, Any]", document))


__all__ = [
    "DEFAULT_POLL_MILLISECONDS",
    "DecodeError",
    "Delivery",
    "decode",
    "from_capture",
    "from_subscription",
]
