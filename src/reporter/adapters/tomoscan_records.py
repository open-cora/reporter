"""Hearing about a scan from TomoScan's own records, rather than documents.

The sibling module translates bluesky documents. TomoScan publishes none:
it is a service on the control network whose progress is visible as
records, so a reporter watching one watches Channel Access and not a
socket. Everything after this module is the same, which is the point of
it being a module: the intents, the relay and the keeper's endpoints do
not know which of the two a report came from.

    a scan ends    StartScan returns to idle
    ended          the two keeper ids, the status, the file
    file           the same ids and the file, for Custody

Two deliveries per scan because a delivery yields one intent, and a
finished scan says two things: how the run went, and that data exists.
Bluesky splits the same pair across a stop document and a resource one.

## Why the ids have to come from the records

`RegisterDataset` needs an execution and a step, and nothing about a
finished scan implies them. So a conductor writes them into two records
before it starts, and this reads them back out of the same records
afterwards. A scan with neither is one somebody ran by hand, which is
ordinary and is ignored rather than held: there is no work in the record
it could belong to.

Reading them back rather than being told is what makes the pair worth
checking. A reporter told which step to file against would file against
it whatever the engine actually did.

## Why it polls

Channel Access offers callbacks, and a generator that yields on one has
to hand values between threads. Polling a handful of records twice a
second costs a beamline nothing measurable and keeps the whole source in
one flow a reader can follow. The cost is that a scan shorter than the
interval could be missed, which is not a tomography scan.

## What it does not read

Everything else TomoScan holds. Its metadata records carry a user's name,
institution, badge and email, and none of that belongs in an event log:
the keeper refuses personal data in events and `RegisterDataset` has
nowhere to put it. The file reference is the whole of what leaves here.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID

import epics

from reporter.intents import Ignored, Intent, RegisterDataset, Report, ReportStepRun, Unmappable

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from reporter.relay import Handle
    from reporter.seams import Delivery
    from reporter.session import Session

ENDED: Final = "ended"
FILE: Final = "file"
"""The two delivery names this source emits, and the translator answers to."""

IDLE: Final = "Done"

START_SCAN: Final = "StartScan"
SCAN_STATUS: Final = "ScanStatus"
FULL_FILE_NAME: Final = "FullFileName"
EXECUTION_ID: Final = "KeeperExecutionId"
STEP_ID: Final = "KeeperStepId"

REPORT_BY_STATUS: Final[dict[str, Report]] = {
    "scan complete": "Completed",
    "scan aborted": "Aborted",
}
"""What TomoScan says it did, in the keeper's words.

Matched in lower case because the text is written for a screen. Anything
absent from this table is `Failed`, which is the safe direction: a scan
whose ending nobody recognised did not demonstrably work.
"""


def from_tomoscan(prefix: str, poll_interval: float = 0.5) -> Iterator[Delivery]:
    """Every scan that finishes on one TomoScan server, as it finishes.

    Does not end, the way a subscription does not end. The caller stops it.
    """
    records = {
        suffix: epics.PV(f"{prefix}{suffix}")
        for suffix in (START_SCAN, SCAN_STATUS, FULL_FILE_NAME, EXECUTION_ID, STEP_ID)
    }

    def text(suffix: str) -> str:
        value = records[suffix].get(as_string=True)
        return "" if value is None else str(value)

    # Whatever the server is doing when this starts is not a scan this saw
    # begin, so the first transition it acts on is the next one.
    was_idle = True
    while True:
        idle = text(START_SCAN) == IDLE
        if idle and not was_idle:
            ended: dict[str, Any] = {
                "execution_id": text(EXECUTION_ID),
                "step_id": text(STEP_ID),
                "status": text(SCAN_STATUS),
                "file": text(FULL_FILE_NAME),
                "origin": f"{prefix}{START_SCAN}",
            }
            yield (ENDED, ended)
            if ended["file"]:
                yield (FILE, ended)
        was_idle = idle
        time.sleep(poll_interval)


def _reference(record: Mapping[str, Any]) -> tuple[UUID, UUID] | None:
    """The pair of ids, or nothing when the pair is not there.

    Both or neither. One id without the other is not a scan half
    attributed, it is a record somebody wrote by hand or a conductor that
    failed between two writes, and guessing the other would file this
    against a step chosen by accident.
    """
    execution, step = str(record.get("execution_id", "")), str(record.get("step_id", ""))
    if not execution or not step:
        return None
    try:
        return UUID(execution), UUID(step)
    except ValueError:
        return None


def _report(status: str) -> Report:
    return REPORT_BY_STATUS.get(status.strip().lower(), "Failed")


def translate(name: str, record: Mapping[str, Any]) -> Intent:
    """One delivery, as the thing it asks this reporter to do."""
    origin = str(record.get("origin", "tomoscan"))
    if name not in (ENDED, FILE):
        return Ignored(f"{name} is not a delivery this source emits")

    reference = _reference(record)
    if reference is None:
        if record.get("execution_id") or record.get("step_id"):
            return Unmappable("a scan carrying one keeper id and not the other", origin)
        return Ignored("a scan carrying no keeper ids, so nobody asked for it")

    execution_id, step_id = reference
    if name == ENDED:
        return ReportStepRun(
            execution_id=execution_id,
            step_id=step_id,
            reported=_report(str(record.get("status", ""))),
            engine_reference=str(record.get("file", "")),
            occurred_at=None,
            origin=origin,
        )
    return RegisterDataset(
        execution_id=execution_id,
        step_id=step_id,
        external_ref_value=str(record.get("file", "")),
        occurred_at=None,
        origin=origin,
    )


def records_into(session: Session) -> Handle:
    """One TomoScan server's records, translated and then acted on.

    The counterpart of `documents_into`, and the only other place this
    reporter is tied to a particular engine. Holds no state, because a
    scan's records say everything about it at the moment it ends, where a
    document stream says it across several documents.
    """

    def handle(name: str, record: Mapping[str, Any]) -> Any:
        return session.act(translate(name, record))

    return handle


__all__ = ["ENDED", "FILE", "REPORT_BY_STATUS", "from_tomoscan", "records_into"]
