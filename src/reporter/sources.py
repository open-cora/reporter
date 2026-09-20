"""Where documents come from, which is the one thing still undecided.

A source is anything that yields `(document name, document)` pairs in the
order an engine emitted them. `Session` and `Relay` take them one at a
time and have no opinion about the origin, so this module is the seam the
subscription lands in when there is one.

There is one source today and it reads a file. A live subscription joins
it here rather than replacing it: replaying a capture is how this gets
tested against a real AROC without a beamline, and that stays useful after
something real exists.

## What a live source will have to decide, and this one does not

Durability. A file has every document and can be read again; a stream has
whatever arrives, once. Which is why the subscription and the checkpoint
are one decision rather than two, and why neither is here yet.
"""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

Delivery = tuple[str, dict[str, Any]]
"""One document, as the stream delivered it: its type name and its body."""


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


__all__ = ["Delivery", "from_capture"]
