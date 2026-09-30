"""Hearing a scan end over Channel Access, and saying what it means.

The translator is pure and most of these drive it directly. The source is
driven against a soft IOC, because the thing worth checking there is that
it reacts to a real transition rather than to a value it was handed.
"""

from __future__ import annotations

import itertools
import os
import threading
import time
from typing import TYPE_CHECKING, Any
from uuid import UUID

import pytest

from reporter.adapters import tomoscan_records as records
from reporter.intents import Ignored, RegisterDataset, ReportStepRun, Unmappable
from tests import _tomoscan_ioc

if TYPE_CHECKING:
    from collections.abc import Iterator

    from reporter.seams import Delivery

EXECUTION = "01a0f013-ce25-7670-8ffb-217d13a9318b"
STEP = "01a0f013-ce25-7670-8ffb-218fa11f5741"
FILE = "/local1/2BM/proposal/scan_007.h5"


def ended(**overrides: Any) -> dict[str, Any]:
    record = {
        "execution_id": EXECUTION,
        "step_id": STEP,
        "status": "Scan complete",
        "file": FILE,
        "origin": "2bmb:TomoScan:StartScan",
    }
    record.update(overrides)
    return record


def test_a_finished_scan_reports_the_run_against_the_step_it_names() -> None:
    intent = records.translate(records.ENDED, ended())
    assert isinstance(intent, ReportStepRun)
    assert (intent.execution_id, intent.step_id) == (UUID(EXECUTION), UUID(STEP))


def test_a_finished_scan_reports_the_file_as_the_name_that_joins() -> None:
    intent = records.translate(records.ENDED, ended())
    assert isinstance(intent, ReportStepRun)
    assert intent.engine_reference == FILE


def test_a_completed_scan_is_reported_completed() -> None:
    intent = records.translate(records.ENDED, ended())
    assert isinstance(intent, ReportStepRun)
    assert intent.reported == "Completed"


def test_an_aborted_scan_is_reported_aborted() -> None:
    intent = records.translate(records.ENDED, ended(status="Scan aborted"))
    assert isinstance(intent, ReportStepRun)
    assert intent.reported == "Aborted"


def test_an_ending_nobody_recognises_is_reported_failed() -> None:
    """The safe direction: an unrecognised ending did not demonstrably work."""
    intent = records.translate(records.ENDED, ended(status="something new"))
    assert isinstance(intent, ReportStepRun)
    assert intent.reported == "Failed"


def test_the_file_delivery_registers_the_dataset_against_the_same_step() -> None:
    intent = records.translate(records.FILE, ended())
    assert isinstance(intent, RegisterDataset)
    assert (intent.execution_id, intent.step_id) == (UUID(EXECUTION), UUID(STEP))
    assert intent.external_ref_value == FILE


def test_a_scan_carrying_no_keeper_ids_is_ignored() -> None:
    """Somebody ran it by hand, and there is no work it could belong to."""
    intent = records.translate(records.ENDED, ended(execution_id="", step_id=""))
    assert isinstance(intent, Ignored)


def test_a_scan_carrying_one_id_and_not_the_other_is_held_rather_than_ignored() -> None:
    """Half a reference is a fault, where none is an ordinary hand-run scan."""
    intent = records.translate(records.ENDED, ended(step_id=""))
    assert isinstance(intent, Unmappable)


def test_an_id_that_is_not_a_uuid_is_not_treated_as_one() -> None:
    intent = records.translate(records.ENDED, ended(execution_id="not-a-uuid"))
    assert isinstance(intent, Unmappable)


def test_a_delivery_this_source_never_emits_is_ignored() -> None:
    assert isinstance(records.translate("descriptor", ended()), Ignored)


def test_the_translator_reports_nothing_of_the_user_to_the_keeper() -> None:
    """TomoScan holds a name, a badge and an email, and none may travel."""
    intent = records.translate(
        records.ENDED, ended(UserName="Jessica", UserEmail="someone@example.org")
    )
    assert isinstance(intent, ReportStepRun)
    assert "Jessica" not in repr(intent)
    assert "example.org" not in repr(intent)


@pytest.fixture(scope="module")
def tomoscan_ioc() -> Iterator[None]:
    """Serve the records for the source test, on a port of its own."""
    for name, value in _tomoscan_ioc.server_environment().items():
        os.environ.setdefault(name, value)
    server = _tomoscan_ioc.start()
    try:
        _tomoscan_ioc.wait_until_serving(server, 30.0)
    except BaseException:
        server.terminate()
        server.wait(timeout=10)
        raise
    yield
    server.terminate()
    server.wait(timeout=10)


@pytest.mark.channel_access
@pytest.mark.usefixtures("tomoscan_ioc")
def test_a_scan_returning_to_idle_is_what_the_source_reacts_to() -> None:
    """Not the value, the change. A server already idle has ended nothing."""
    import epics

    prefix = _tomoscan_ioc.PREFIX
    for suffix, value in (
        ("KeeperExecutionId", EXECUTION),
        ("KeeperStepId", STEP),
        ("FullFileName", FILE),
    ):
        epics.caput(f"{prefix}{suffix}", value, wait=True, timeout=10)

    collected: list[Delivery] = []

    def gather() -> None:
        # pyepics binds a context per thread, and a channel opened in one
        # is not usable from another. Without this the generator's own PVs
        # raise about an unexpected channel id rather than reading.
        epics.ca.use_initial_context()
        collected.extend(itertools.islice(records.from_tomoscan(prefix, 0.05), 4))

    reader = threading.Thread(target=gather, daemon=True)
    reader.start()

    def toggle_until(wanted: int) -> None:
        # Driven in a loop rather than once, because the source acts on a
        # transition it saw: a single scan ended before its first poll
        # would look exactly like a server that was always idle, and the
        # test would fail on a slow machine rather than on a broken
        # adapter.
        deadline = time.monotonic() + 20
        while len(collected) < wanted and time.monotonic() < deadline:
            epics.caput(f"{prefix}StartScan", 1, wait=True, timeout=10)
            time.sleep(0.2)
            epics.caput(f"{prefix}StartScan", 0, wait=True, timeout=10)
            time.sleep(0.2)

    toggle_until(2)

    # The half the assertions below cannot see, and the reason this reads
    # four rather than two. One scan has ended, so a source keyed on the
    # value instead of on the change goes on yielding every poll while the
    # server sits idle, and every field it yields is still correct. Only
    # the count tells the two apart. Asserting it here rather than before
    # the toggle is what makes it mean something: the reader has just
    # answered, so it is known to be connected and polling, and an empty
    # list cannot be a reader that had not started yet.
    time.sleep(1.0)
    assert len(collected) == 2, (
        "An idle server that stays idle has ended nothing. Yielding again "
        "means the source is reading the value rather than the change."
    )

    toggle_until(4)
    reader.join(timeout=5)

    assert [name for name, _ in collected[:2]] == [records.ENDED, records.FILE]
    assert collected[0][1]["execution_id"] == EXECUTION
    assert collected[1][1]["file"] == FILE
