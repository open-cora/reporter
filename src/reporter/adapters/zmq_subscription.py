"""Delivering, from an engine publishing over 0MQ.

The source that makes this a reporter rather than a replay tool. It
reads the socket and the encoding and nothing else, which is why the
engine's own library is not a dependency: the frame is a prefix, a name
and a msgpack payload separated by single spaces, and reading it through
the engine would drag that engine in, numpy included, to a package whose
claim is that it is not the engine.

## A third way in, which needs no code here

An engine in the same process hands deliveries over directly, because
`Relay.submit` already has the signature a subscription callback wants:

    RE.subscribe(relay.submit)

That is not a source and cannot be one. A source is pulled from and a
callback is pushed to, and when the engine is in this process there is
nothing to pull. See the README for the whole recipe.

## What is still undecided, and it is no longer liveness

Durability. 0MQ publish and subscribe is fire and forget: a subscriber
that is not running when a delivery goes out never learns it existed,
and there is no offset to come back to. That is at-most-once, which is
what `Relay` already says this reporter is, and closing it means a
transport that keeps a log rather than anything in this module.
"""

from __future__ import annotations

from contextlib import closing
from typing import TYPE_CHECKING, Any, Final, cast

if TYPE_CHECKING:
    from collections.abc import Generator

    from reporter.seams import Delivery

DEFAULT_POLL_MILLISECONDS: Final = 500
"""How long a subscription waits for a delivery before looking up.

It is not a timeout and nothing is lost by it: 0MQ queues what arrives
while nobody is asking. It is how often the loop reaches a point where
an interrupt can land, which is the difference between a process that
stops on Ctrl-C and one that has to be killed.
"""


class LibrariesAbsentError(ImportError):
    """A subscription was asked for without the libraries it is an extra for."""

    def __init__(self, missing: ImportError) -> None:
        super().__init__(
            "Reading a published document stream needs the subscribe extra. "
            f"Re-sync with --extra subscribe. ({missing})"
        )


class DecodeError(Exception):
    """A frame arrived that this cannot read as a published delivery."""


def from_subscription(
    address: str,
    *,
    prefix: bytes = b"",
    poll_milliseconds: int = DEFAULT_POLL_MILLISECONDS,
) -> Generator[Delivery]:
    """Deliveries from an engine publishing over 0MQ, until interrupted.

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
    zmq = _zmq()
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


def _zmq() -> Any:
    """The socket library, imported where it is reached rather than above.

    Both libraries below belong to an extra, and `__main__` imports this
    module whichever source a deployment is running. Importing them at
    the top therefore made the whole process need them, so a reporter
    installed for a Channel Access beamline could not start at all.
    Measured, not reasoned: `python -m reporter` raised
    `ModuleNotFoundError: msgpack` on an install carrying the two extras
    the deploy script actually passes.

    The pairing the pyproject describes is unchanged. This module is
    still the only one that names either library, and a deployment that
    never subscribes still installs neither.
    """
    try:
        import zmq
    except ImportError as missing:
        raise LibrariesAbsentError(missing) from missing
    return zmq


def _msgpack() -> Any:
    """The encoding, imported where it is reached. See the note above."""
    try:
        import msgpack
    except ImportError as missing:
        raise LibrariesAbsentError(missing) from missing
    return msgpack


def decode(frame: bytes) -> Delivery:
    """One published frame, as a delivery.

    The frame is a prefix, a name and a payload, separated by single
    spaces, and the payload is the body:

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
        body = _msgpack().unpackb(payload)
    except Exception as unreadable:
        raise DecodeError(
            f"The payload of a {name.decode(errors='replace')!r} frame is not msgpack. "
            "A publisher encodes with pickle unless it is told not to, and this refuses "
            "to unpickle anything that arrives over a socket. Construct the publisher "
            "with serializer=msgpack.dumps."
        ) from unreadable

    if not isinstance(body, dict):
        raise DecodeError(
            f"A {name.decode(errors='replace')!r} frame carried {type(body).__name__} "
            "rather than a mapping."
        )

    # The keys are a claim rather than a check. msgpack hands back whatever
    # was encoded, and walking every key of every payload to prove they are
    # strings would cost a scan per delivery to learn what the format
    # already guarantees.
    return (name.decode(), cast("dict[str, Any]", body))


__all__ = ["DEFAULT_POLL_MILLISECONDS", "DecodeError", "decode", "from_subscription"]
