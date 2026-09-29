"""Delivering, from a capture on disk.

How the whole path gets tested against a real keeper without a beamline,
and it keeps doing that after a live subscription exists: it needs no
engine, and it is the same shipped code either way.

It imports nothing but the standard library, which is the point of it
being its own module rather than sharing one with the subscription.
Something embedding this reporter to replay a capture pulls in neither
the socket library nor the encoding. The command does, because
`__main__` names every adapter it can pick between and picking is what
an entrypoint is for.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from reporter.seams import Delivery


def from_capture(path: Path) -> Iterator[Delivery]:
    """Every delivery in a capture, flattened into one stream.

    The capture groups its contents by scenario, because the collector
    that wrote it drove one scenario at a time. A reporter sees one stream, so they
    are flattened into one here, which is also closer to what a
    subscription delivers.
    """
    captured: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    for scenario in captured.values():
        entries: list[dict[str, Any]] = scenario["documents"]
        for entry in entries:
            yield (str(entry["name"]), dict(entry["doc"]))


__all__ = ["from_capture"]
