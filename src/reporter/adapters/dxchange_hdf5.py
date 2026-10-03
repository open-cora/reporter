"""Describing, for a tomography file written to the DXchange convention.

## What it reports and what it refuses

The arrays under `/exchange` one at a time, because those are the data and
the convention's names for them are the only place their meaning is written.
Everything else as a region: named, counted, and not opened further.

A real file at 19-BM holds 140 nodes, 109 of them datasets, and comes back
here as eight entries. The 130-odd it does not enumerate are the per-value
metadata, which is read by opening the file rather than by indexing it. That
line is the whole difference between this and a cache of the file's contents.

## Where it stops descending

One rule rather than a list of paths, so a file with a group nobody has seen
before still comes back named. Below the top level, a group whose children
are all groups is descended into once, and anything else is reported where it
stands. That puts `/measurement` at its three parts, which mean different
things, and leaves `/defaults` whole, because its children are the per-frame
arrays rather than further sections.

## Roles, and why most paths do not get one

A role is the word a different convention would also reach for, so it exists
for convergence rather than explanation. `/exchange/data` needs one badly:
nothing in that path says it holds projections. `/measurement/ancillary`
holds a single barometric pressure reading at this beamline, which is not
enough to name a category, so it gets none and says so by absence.

## What the absence of theta means

A scan engine appends `/exchange/theta` after the writing plugin has closed
the file, and a dataset of projections without it cannot be reconstructed.
That has happened: sixty thousand projections were left without angles when
the thread writing them died. So this never invents the entry, and a caller
asking too early will see it missing on a healthy file, which is why the
seam says to ask once the work has ended rather than once the file closed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

import h5py

from reporter.seams import (
    MANIFEST_MAX_ENTRIES,
    Entry,
    Extent,
    Manifest,
    UnavailableError,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

CONVENTION: Final = "dxchange"
"""The vocabulary the roles below are drawn from."""

DATA_GROUP: Final = "/exchange"
"""Where the convention puts the data, and the one group opened array by array."""

ROLES: Final[dict[str, str]] = {
    "/exchange/data": "projections",
    "/exchange/data_white": "flat-fields",
    "/exchange/data_dark": "dark-fields",
    "/exchange/theta": "projection-angles",
    "/process/acquisition": "acquisition-plan",
    "/measurement/instrument": "instrument-state",
    "/measurement/sample": "experiment-context",
    "/defaults": "frame-index",
}
"""What this convention calls each thing, for the paths it names.

Deliberately not exhaustive. A path absent from here is reported with no
role, which says nobody knows rather than that there is nothing, and those
are different answers.

Two of these read oddly against the path and are right anyway.
`/measurement/sample` is called experiment context because the sample is four
of its seventeen leaves and the rest is the proposal, the people and the
output location. `/defaults` is called a frame index because it holds a
timestamp and an identifier per frame, and the engine reads those to work out
which frames were projections.
"""


class DxchangeHdf5Describing:
    """Says what is inside one DXchange file, by opening it and not its data."""

    def describe(self, address: str) -> Manifest | None:
        """The file at this address, or `None` if it is not this convention.

        The address is the value that was filed, with no scheme on it, so
        this is told at build time that such a value names a path. That is
        the same arrangement filing uses for the scheme itself.

        A file that opens and holds no data group is not a failure and is
        not described: some other adapter understands it, or none does.
        """
        try:
            with h5py.File(address, "r") as opened:
                if DATA_GROUP.lstrip("/") not in opened:
                    return None
                entries = tuple(_entries(opened))
        except OSError as unreadable:
            raise UnavailableError(f"describe {address}: {unreadable}") from unreadable
        if len(entries) > MANIFEST_MAX_ENTRIES:
            entries = tuple(_coarse(entries))
        return Manifest(convention=CONVENTION, entries=entries)


def _entries(opened: Any) -> Iterator[Entry]:
    for name in opened:
        node = opened[name]
        path = f"/{name}"
        if path == DATA_GROUP or _all_groups(node):
            yield from (_describe(node[child], f"{path}/{child}") for child in node)
        else:
            yield _describe(node, path)


def _coarse(entries: tuple[Entry, ...]) -> Iterator[Entry]:
    """One entry per top-level name, for a file too wide to describe finely.

    The bound is a contract rather than a place to stop counting, so a file
    that would exceed it is summarized instead of truncated. Handing back the
    first sixty-four of something would look complete and would not be.
    """
    seen: dict[str, int] = {}
    for entry in entries:
        top = "/" + entry.path.lstrip("/").split("/")[0]
        seen[top] = seen.get(top, 0) + 1
    for top, count in seen.items():
        yield Entry(path=top, extent=Extent((count,), None, None), role=ROLES.get(top))


def _describe(node: Any, path: str) -> Entry:
    if isinstance(node, h5py.Group):
        return Entry(path=path, extent=Extent((_beneath(node),), None, None), role=ROLES.get(path))
    return Entry(path=path, extent=_array_extent(node), role=ROLES.get(path))


def _array_extent(dataset: Any) -> Extent:
    """An array's dimensions, its element type, and what it reserved.

    A capacity is reported only where it says something the shape does not.
    A dataset created at a fixed size reports its own shape as its maximum,
    which would stamp every entry with a number that merely repeats the one
    beside it. An unlimited dimension comes back as nothing at all, because
    a tuple of counts has no way to spell unbounded and inventing a sentinel
    for it would be worse than saying the container did not say.
    """
    shape = tuple(int(dimension) for dimension in dataset.shape)
    limit = tuple(dataset.maxshape)
    capacity = (
        tuple(int(dimension) for dimension in limit)
        if None not in limit and tuple(limit) != shape
        else None
    )
    return Extent(shape=shape, capacity=capacity, dtype=str(dataset.dtype))


def _all_groups(node: Any) -> bool:
    if not isinstance(node, h5py.Group):
        return False
    children: list[Any] = list(node)
    return all(isinstance(node[child], h5py.Group) for child in children)


def _beneath(group: Any) -> int:
    """How many nodes a region holds, all the way down.

    Counted rather than listed, which is the point of calling it a region.
    """
    total = 0

    def count(_name: str) -> None:
        nonlocal total
        total += 1

    group.visit(count)
    return total


__all__ = ["CONVENTION", "DATA_GROUP", "ROLES", "DxchangeHdf5Describing"]
