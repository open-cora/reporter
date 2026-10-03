"""Saying what is inside the data, after saying where it is.

A second act on a record that already exists, and the whole of what
this file is about is that it stays second. The dataset is filed before
anything tries to read the container, and nothing the reader or the
keeper does to the attempt is allowed to cost that.

Driven through a real `Session` with fakes on both halves of the leg,
because what could be wrong is the ordering and the failure handling
rather than anything a round trip would show.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from reporter.intents import RegisterDataset, ReportStepRun
from reporter.outcomes import Held, Kept
from reporter.seams import (
    DisagreedError,
    Entry,
    Extent,
    Manifest,
    RefusedError,
    UnavailableError,
)
from reporter.session import Session
from tests._fakes import Catalogue, Reader, Recorder, Store

ADDRESS = "/local1/scan_034.h5"
WHEN = datetime(2026, 9, 19, 14, 30, tzinfo=UTC)

FRAMES = Entry(
    path="/exchange/data",
    extent=Extent(shape=(1800, 2048, 2048), capacity=None, dtype="uint16"),
    role="projections",
)
ANGLES = Entry(path="/exchange/theta", extent=None, role="projection-angles")


def _manifest(*entries: Entry) -> Manifest:
    return Manifest(convention="dxchange", entries=entries or (FRAMES,))


class _Reports:
    """Accepts every report, which is not what any of these are about."""

    def record(self, intent: ReportStepRun) -> None:
        _ = intent


class _Files:
    """Mints one id for every dataset, or refuses them all.

    Two classes where the keeper adapter has two, rather than one
    object standing in for both seams. A single `record` would have to
    take either intent and return either nothing or an id, which is a
    signature that satisfies neither protocol and a fake that proves
    nothing about the shapes it stands in for.
    """

    def __init__(self, refusal: Exception | None = None) -> None:
        self.dataset_id = uuid4()
        self.filed: list[RegisterDataset] = []
        self._refusal = refusal

    def record(self, intent: RegisterDataset) -> UUID:
        if self._refusal is not None:
            raise self._refusal
        self.filed.append(intent)
        return self.dataset_id


def _registration() -> RegisterDataset:
    return RegisterDataset(
        execution_id=uuid4(),
        step_id=uuid4(),
        external_ref_value=ADDRESS,
        occurred_at=WHEN,
        origin="a-scan",
    )


def _session(
    reader: Reader | None = None, catalogue: Catalogue | None = None
) -> tuple[Session, _Files]:
    filing = _Files()
    return Session(_Reports(), filing, Store(), reader, catalogue), filing


def test_a_filed_dataset_is_described_against_the_address_that_was_filed() -> None:
    reader = Reader(manifests={ADDRESS: _manifest(FRAMES, ANGLES)})
    catalogue = Catalogue()
    session, filing = _session(reader, catalogue)

    outcome = session.act(_registration())

    assert isinstance(outcome, Kept)
    assert outcome.undescribed is None
    assert reader.asked == [ADDRESS]
    assert catalogue.filed == [(filing.dataset_id, ADDRESS, _manifest(FRAMES, ANGLES))]


def test_a_deployment_that_describes_nothing_files_the_address_and_says_so() -> None:
    """The ordinary case at a beamline with no adapter for its format."""
    session, _filing = _session()

    outcome = session.act(_registration())

    assert isinstance(outcome, Kept)
    assert outcome.undescribed is None, "describing nothing is not a thing to report"


def test_half_a_contents_leg_describes_nothing_rather_than_reading_for_nobody() -> None:
    reader = Reader(manifests={ADDRESS: _manifest()})
    session, _filing = _session(reader, None)

    outcome = session.act(_registration())

    assert isinstance(outcome, Kept)
    assert reader.asked == [], "a reader with nowhere to send what it finds is not asked"


def test_a_container_the_reader_does_not_understand_is_reported_not_invented() -> None:
    session, _filing = _session(Reader(manifests={}), Catalogue())

    outcome = session.act(_registration())

    assert isinstance(outcome, Kept)
    assert outcome.undescribed is not None
    assert ADDRESS in outcome.undescribed


@pytest.mark.parametrize(
    "failure",
    [
        UnavailableError("the file is not readable yet"),
        RefusedError("not granted that command"),
        DisagreedError("that description is already held"),
        RuntimeError("the format library did something nobody mapped"),
    ],
    ids=["unavailable", "refused", "disagreed", "unmapped"],
)
def test_a_reader_that_fails_any_way_at_all_still_leaves_the_dataset_filed(
    failure: Exception,
) -> None:
    """Including the kind that would otherwise mean ask again.

    Letting one propagate would retry the whole delivery, re-sending a
    report and re-filing an address that both landed, and then report
    the delivery held. The last case is not one the seams promise, and
    is the one that would kill the relay's worker.
    """
    catalogue = Catalogue()
    session, filing = _session(Reader(refusal=failure), catalogue)

    outcome = session.act(_registration())

    assert isinstance(outcome, Kept)
    assert outcome.dataset_id == filing.dataset_id
    assert len(filing.filed) == 1
    assert outcome.undescribed is not None
    assert catalogue.filed == []


def test_a_keeper_that_refuses_the_description_still_leaves_the_dataset_filed() -> None:
    reader = Reader(manifests={ADDRESS: _manifest()})
    session, filing = _session(reader, Catalogue(refusal=RefusedError("no")))

    outcome = session.act(_registration())

    assert isinstance(outcome, Kept)
    assert outcome.dataset_id == filing.dataset_id
    assert outcome.undescribed is not None


def test_a_dataset_that_cannot_be_filed_is_never_described() -> None:
    """Nothing to describe against, and nowhere to hang the answer."""
    reader = Reader(manifests={ADDRESS: _manifest()})
    catalogue = Catalogue()
    refusing = _Files(refusal=RefusedError("the keeper would not take it"))
    session = Session(_Reports(), refusing, Store(), reader, catalogue)

    outcome = session.act(_registration())

    assert isinstance(outcome, Held)
    assert reader.asked == []
    assert catalogue.filed == []


def test_every_describer_the_configuration_accepts_is_one_the_entrypoint_can_build() -> None:
    """The two sides of the registry, which are written in two files.

    `config.DESCRIBERS` is what a typo is checked against at load, and
    `contents_leg` is what actually builds one. A name listed in the
    first and missing from the second would pass configuration and then
    raise on the first scan that ended, which is exactly the failure
    load-time validation exists to prevent.
    """
    from reporter.__main__ import contents_leg
    from reporter.config import DESCRIBERS, from_mapping

    for name in sorted(DESCRIBERS):
        config = from_mapping(
            {
                "keeper": {"base_url": "https://keeper.example", "token": "a-token"},
                "dataset": {"external_ref_scheme": "posix-file", "describer": name},
            }
        )
        describing, cataloguing = contents_leg(Recorder(answers=[]), config)
        assert describing is not None, name
        assert cataloguing is not None, name


def test_a_configuration_naming_no_describer_builds_neither_half() -> None:
    from reporter.__main__ import contents_leg
    from reporter.config import from_mapping

    config = from_mapping(
        {
            "keeper": {"base_url": "https://keeper.example", "token": "a-token"},
            "dataset": {"external_ref_scheme": "posix-file"},
        }
    )

    assert contents_leg(Recorder(answers=[]), config) == (None, None)


def test_asking_for_a_describer_this_install_cannot_build_is_refused_at_startup() -> None:
    """Configuration cannot catch this: the name is good, the venv is short.

    The deploy script passes `--extra service --extra epics` and not
    `--extra describe-hdf5`, so a beamline that turns describing on and
    does not change the install has a perfectly valid configuration and
    no format library. Saying so at startup is the difference between a
    message and a month of scans nobody described.
    """
    import sys

    from reporter.__main__ import contents_leg
    from reporter.config import ConfigError, from_mapping

    config = from_mapping(
        {
            "keeper": {"base_url": "https://keeper.example", "token": "a-token"},
            "dataset": {"external_ref_scheme": "posix-file", "describer": "dxchange-hdf5"},
        }
    )

    class _NoH5py:
        def find_spec(self, name: str, path: object = None, target: object = None) -> None:
            _ = path, target
            if name.split(".")[0] == "h5py":
                raise ModuleNotFoundError(f"No module named {name!r}")
            return None

    evicted = {n: m for n, m in sys.modules.items() if n.split(".")[0] in {"h5py"}}
    for name in evicted:
        del sys.modules[name]
    sys.modules.pop("reporter.adapters.dxchange_hdf5", None)
    blocker = _NoH5py()
    sys.meta_path.insert(0, blocker)
    try:
        with pytest.raises(ConfigError, match="describe-hdf5"):
            contents_leg(Recorder(answers=[]), config)
    finally:
        sys.meta_path.remove(blocker)
        sys.modules.pop("reporter.adapters.dxchange_hdf5", None)
        sys.modules.update(evicted)
