"""What the DXchange describer reports, against the real file's shape.

`tests/dxchange_nodes.txt` is a capture: `h5ls -r` of a 12 GB file at 19-BM, 140
nodes of it. The structure test rebuilds that tree at a size a test can hold
and asserts the walk comes back with eight entries, which is the claim the
whole design rests on.

The rest are hand-built, because each is about one rule and a real file
happens to exercise only some of them.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import h5py
import pytest

from reporter.adapters.dxchange_hdf5 import DxchangeHdf5Describing
from reporter.seams import Describing, UnavailableError

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

CAPTURE = Path(__file__).parent / "dxchange_nodes.txt"


def _open(path: Path | str, mode: str) -> Any:
    """The one place this suite admits that the format library is untyped.

    h5py is C-backed and reports partially unknown types, which a strict
    checker refuses at every call. Letting it in here once keeps that to a
    single annotated boundary instead of an ignore beside each write.
    """
    return h5py.File(path, mode)


NODE = re.compile(r"^(?P<path>\S+)\s+(?P<kind>Group|Dataset)")

EXPECTED = (
    ("/defaults", "frame-index"),
    ("/exchange/data", "projections"),
    ("/exchange/data_dark", "dark-fields"),
    ("/exchange/data_white", "flat-fields"),
    ("/measurement/ancillary", None),
    ("/measurement/instrument", "instrument-state"),
    ("/measurement/sample", "experiment-context"),
    ("/process/acquisition", "acquisition-plan"),
)


def _captured() -> Mapping[str, str]:
    """Every node the real file holds, as path to Group or Dataset."""
    found: dict[str, str] = {}
    for line in CAPTURE.read_text(encoding="utf-8").splitlines():
        matched = NODE.match(line)
        if matched and matched["path"] != "/":
            found["/" + matched["path"].lstrip("/")] = matched["kind"]
    return found


def _rebuild(into: Path, nodes: Mapping[str, str]) -> Path:
    """The captured tree at a size a test can hold.

    Shapes are not reproduced. This test is about which entries the walk
    returns and what they are called, and a faithful 9568 by 6380 would be
    about how much disk a suite may use.
    """
    with _open(into, "w") as built:
        for path, kind in sorted(nodes.items()):
            if kind == "Group":
                built.require_group(path)
            else:
                built.create_dataset(path, shape=(1,), dtype="uint16")
    return into


def test_the_capture_holds_the_file_it_claims_to() -> None:
    """A capture that stopped matching is a fixture nobody is checking."""
    nodes = _captured()
    assert len(nodes) == 139, "140 lines, one of which is the root"
    assert sum(1 for kind in nodes.values() if kind == "Dataset") == 109
    assert "/exchange/data" in nodes
    assert "/exchange/theta" not in nodes, "no 19-BM file carries one"


def test_the_real_tree_comes_back_as_eight_entries_with_their_roles(tmp_path: Path) -> None:
    described = DxchangeHdf5Describing().describe(str(_rebuild(tmp_path / "real.h5", _captured())))
    assert described is not None
    assert tuple(sorted((entry.path, entry.role) for entry in described.entries)) == EXPECTED
    assert described.convention == "dxchange"


def test_a_region_is_counted_all_the_way_down_rather_than_listed(tmp_path: Path) -> None:
    described = DxchangeHdf5Describing().describe(str(_rebuild(tmp_path / "real.h5", _captured())))
    assert described is not None
    counted = {entry.path: entry.extent for entry in described.entries}
    instrument = counted["/measurement/instrument"]
    assert instrument is not None
    assert instrument.shape == (75,), "the nodes beneath it, not its direct children"
    assert instrument.dtype is None, "a region has no element type"


def _dxchange(into: Path, arrays: Sequence[tuple[str, tuple[int, ...], object]]) -> str:
    with _open(into, "w") as built:
        for name, shape, maxshape in arrays:
            built.create_dataset(name, shape=shape, maxshape=maxshape, dtype="uint16")
    return str(into)


def test_a_fixed_array_reports_no_capacity_because_it_would_repeat_the_shape(
    tmp_path: Path,
) -> None:
    described = DxchangeHdf5Describing().describe(
        _dxchange(tmp_path / "f.h5", [("/exchange/data", (4, 2, 2), None)])
    )
    assert described is not None
    extent = described.entries[0].extent
    assert extent is not None
    assert extent.shape == (4, 2, 2)
    assert extent.capacity is None


def test_an_array_that_reserved_more_than_it_holds_reports_what_it_reserved(
    tmp_path: Path,
) -> None:
    """The one flat field against the hundred that were planned for."""
    described = DxchangeHdf5Describing().describe(
        _dxchange(tmp_path / "f.h5", [("/exchange/data_white", (1, 2, 2), (100, 2, 2))])
    )
    assert described is not None
    extent = described.entries[0].extent
    assert extent is not None
    assert (extent.shape, extent.capacity) == ((1, 2, 2), (100, 2, 2))


def test_an_unlimited_dimension_reports_no_capacity_rather_than_a_sentinel(
    tmp_path: Path,
) -> None:
    described = DxchangeHdf5Describing().describe(
        _dxchange(tmp_path / "f.h5", [("/exchange/data", (3, 2, 2), (None, 2, 2))])
    )
    assert described is not None
    extent = described.entries[0].extent
    assert extent is not None
    assert extent.capacity is None


def test_angles_that_were_never_written_are_missing_rather_than_invented(
    tmp_path: Path,
) -> None:
    """The failure this exists to make visible, as an absent entry."""
    described = DxchangeHdf5Describing().describe(
        _dxchange(tmp_path / "f.h5", [("/exchange/data", (4, 2, 2), None)])
    )
    assert described is not None
    assert "/exchange/theta" not in {entry.path for entry in described.entries}


def test_angles_that_were_appended_after_the_close_are_reported_with_their_role(
    tmp_path: Path,
) -> None:
    path = _dxchange(tmp_path / "f.h5", [("/exchange/data", (4, 2, 2), None)])
    with _open(path, "a") as reopened:
        reopened.create_dataset("/exchange/theta", data=[0.0, 0.5, 1.0, 1.5])
    described = DxchangeHdf5Describing().describe(path)
    assert described is not None
    angles = {entry.path: entry.role for entry in described.entries}
    assert angles["/exchange/theta"] == "projection-angles"


def test_a_group_no_convention_names_is_reported_and_counted_without_a_role(
    tmp_path: Path,
) -> None:
    path = _dxchange(tmp_path / "f.h5", [("/exchange/data", (4, 2, 2), None)])
    with _open(path, "a") as reopened:
        reopened.create_dataset("/surprise/thing", shape=(1,), dtype="uint16")
    described = DxchangeHdf5Describing().describe(path)
    assert described is not None
    unknown = {entry.path: entry for entry in described.entries}["/surprise"]
    assert unknown.role is None
    assert unknown.extent is not None and unknown.extent.shape == (1,)


def test_a_file_with_no_data_group_is_not_this_convention_and_answers_none(
    tmp_path: Path,
) -> None:
    other = tmp_path / "other.h5"
    with _open(other, "w") as built:
        built.create_dataset("/entry/instrument/detector/data", shape=(1,), dtype="uint16")
    assert DxchangeHdf5Describing().describe(str(other)) is None


def test_a_file_that_cannot_be_opened_raises_rather_than_answering_none(tmp_path: Path) -> None:
    with pytest.raises(UnavailableError):
        DxchangeHdf5Describing().describe(str(tmp_path / "never-written.h5"))


def test_a_file_too_wide_to_describe_finely_is_summarized_not_truncated(
    tmp_path: Path,
) -> None:
    wide = tmp_path / "wide.h5"
    with _open(wide, "w") as built:
        for index in range(80):
            built.create_dataset(f"/exchange/data_{index}", shape=(1,), dtype="uint16")
        built.create_dataset("/exchange/data", shape=(1,), dtype="uint16")
    described = DxchangeHdf5Describing().describe(str(wide))
    assert described is not None
    assert tuple(entry.path for entry in described.entries) == ("/exchange",)
    assert described.entries[0].extent is not None
    assert described.entries[0].extent.shape == (81,), "all of them, not the first sixty-four"


def test_the_adapter_satisfies_the_seam_it_is_written_against() -> None:
    assert isinstance(DxchangeHdf5Describing(), Describing)
