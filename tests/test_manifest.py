"""What a manifest may hold, and the things it refuses to become.

A manifest exists so a reader can decide whether to open a body of data.
Most of these check that it cannot also be used to avoid opening it,
which is the one way this would stop being worth having.
"""

from __future__ import annotations

import dataclasses

import pytest

from reporter.seams import (
    ENTRY_PATH_MAX_LENGTH,
    LABEL_MAX_LENGTH,
    MANIFEST_MAX_ENTRIES,
    Describing,
    Entry,
    Extent,
    InvalidManifestError,
    Manifest,
)
from tests._fakes import Reader

FRAMES = Entry(
    path="/exchange/data",
    extent=Extent(shape=(100, 6380, 9568), capacity=None, dtype="uint16"),
    role="projections",
)


def test_an_entry_has_no_field_that_could_hold_a_value_read_from_the_data() -> None:
    """The guard the whole design rests on, as a shape rather than a rule.

    A description that could carry a mean would let a reader answer
    instead of opening, which is the difference between an index and a
    cache. Adding a field here is allowed only after that argument has
    been had again.
    """
    assert [field.name for field in dataclasses.fields(Entry)] == ["path", "extent", "role"]
    assert [field.name for field in dataclasses.fields(Extent)] == [
        "shape",
        "capacity",
        "dtype",
    ]


def test_a_manifest_carries_the_convention_its_roles_are_drawn_from() -> None:
    manifest = Manifest(convention="dxchange", entries=(FRAMES,))
    assert manifest.convention == "dxchange"
    assert manifest.entries[0].role == "projections"


def test_an_entry_whose_convention_names_nothing_carries_no_role() -> None:
    unnamed = Entry(path="image_000001.tif", extent=Extent((2000,), None, None), role=None)
    assert Manifest(convention="unknown", entries=(unnamed,)).entries[0].role is None


def test_a_role_given_as_an_empty_string_is_refused_so_absence_has_one_spelling() -> None:
    with pytest.raises(InvalidManifestError, match="absent as None"):
        Entry(path="/exchange/data", extent=None, role="")


def test_a_dtype_given_as_an_empty_string_is_refused_for_the_same_reason() -> None:
    with pytest.raises(InvalidManifestError, match="absent as None"):
        Extent(shape=(1,), capacity=None, dtype="   ")


def test_a_capacity_records_what_a_container_reserved_beside_what_it_holds() -> None:
    """The one flat field against the hundred that were planned for."""
    flats = Extent(shape=(1, 6380, 9568), capacity=(100, 6380, 9568), dtype="uint16")
    assert flats.shape[0] == 1
    assert flats.capacity is not None
    assert flats.capacity[0] == 100


def test_a_capacity_of_a_different_rank_than_its_shape_is_refused() -> None:
    with pytest.raises(InvalidManifestError, match="same number of dimensions"):
        Extent(shape=(1, 6380), capacity=(100,), dtype=None)


def test_a_shape_counting_a_negative_number_of_things_is_refused() -> None:
    with pytest.raises(InvalidManifestError, match="cannot hold a negative"):
        Extent(shape=(-1,), capacity=None, dtype=None)


def test_an_entry_with_a_blank_path_is_refused_because_it_names_nowhere() -> None:
    with pytest.raises(InvalidManifestError, match="cannot be blank"):
        Entry(path="  ", extent=None, role="projections")


def test_a_path_past_the_bound_is_refused_as_a_payload() -> None:
    with pytest.raises(InvalidManifestError, match="becoming a payload"):
        Entry(path="/" + "d" * ENTRY_PATH_MAX_LENGTH, extent=None, role=None)


def test_a_label_past_the_bound_is_refused_as_not_a_vocabulary_word() -> None:
    with pytest.raises(InvalidManifestError, match="short word"):
        Entry(path="/exchange/data", extent=None, role="p" * (LABEL_MAX_LENGTH + 1))


def test_a_blank_convention_is_refused_because_unknown_is_the_honest_value() -> None:
    with pytest.raises(InvalidManifestError, match="says nothing at all"):
        Manifest(convention="", entries=())


def test_a_manifest_enumerating_a_whole_tree_is_refused_at_the_bound() -> None:
    """The real file has 140 nodes and is described by five entries."""
    too_many = tuple(
        Entry(path=f"/node/{index}", extent=None, role=None)
        for index in range(MANIFEST_MAX_ENTRIES + 1)
    )
    with pytest.raises(InvalidManifestError, match="summarized before it is described"):
        Manifest(convention="dxchange", entries=too_many)


def test_a_manifest_at_the_bound_is_allowed_so_the_limit_is_not_off_by_one() -> None:
    allowed = tuple(
        Entry(path=f"/node/{index}", extent=None, role=None)
        for index in range(MANIFEST_MAX_ENTRIES)
    )
    assert len(Manifest(convention="dxchange", entries=allowed).entries) == MANIFEST_MAX_ENTRIES


def test_a_manifest_holding_no_entries_is_allowed_and_is_not_an_absent_answer() -> None:
    """A container a reader understood and found empty is not the same as
    one it could not read, which is what `None` from the seam says."""
    assert Manifest(convention="dxchange", entries=()).entries == ()


def test_a_reader_satisfies_the_describing_seam_by_the_shape_of_its_call() -> None:
    assert isinstance(Reader(), Describing)


def test_a_container_the_reader_does_not_understand_answers_none_rather_than_empty() -> None:
    reader = Reader()
    assert reader.describe("posix-file:/local/vieworks_test/test_249.h5") is None
    assert reader.asked == ["posix-file:/local/vieworks_test/test_249.h5"]
