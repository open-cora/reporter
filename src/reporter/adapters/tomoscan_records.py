"""Hearing about a scan from TomoScan's own records, rather than documents.

The sibling module translates bluesky documents. TomoScan publishes none:
it is a service on the control network whose progress is visible as
records, so a reporter watching one watches Channel Access and not a
socket. Everything after this module is the same, which is the point of
it being a module: the intents, the relay and the keeper's endpoints do
not know which of the two a report came from.

    a scan begins  StartScan leaves idle
    started        the two keeper ids and the identifier of the new run
    a scan ends    StartScan returns to idle
    ended          the same ids, the status, and the identifier again
    file           the same ids and the address, for Custody

Three deliveries per scan because a delivery yields one intent, and a
scan says three things: that a run opened, how it went, and that data
exists. Bluesky splits the same across a start, a stop and a resource
document.

## Why a start is reported at all

It was not, and every ending this source sent was refused. The keeper
holds an engine's account of a run as a state machine whose genesis is a
start, so a `Completed` arriving against a step with nothing reported
yet does not follow and comes back 409. Measured at a commissioned
beamline, where every scan reported `Unchanged` and the engine state
stayed null for all of them.

## The two records that are not there yet when their edge arrives

Neither of the things that identify a run is readable at the moment the
edge announcing it arrives, and in both cases the record still holds the
previous scan's value:

    StartScan   Acquire        the scan begins
    ScanUUID    a new uuid     written just after, by begin_scan
    StartScan   Done           the scan ends
    FullFileName  the path     written just after, by end_scan

So neither is read on its edge. Each is waited for, and what is waited
for is the value changing rather than the value being anything in
particular. `ScanUUID` is autosaved upstream and nothing blanks it
between scans, so "it is not empty" would be true of the previous run's
id for the whole of this one. Only the change is news.

A wait that runs out yields anyway rather than dropping the scan. A run
nobody can name is still a run that happened, and an ending nobody
reported is the silence this whole source exists to break.

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

STARTED: Final = "started"
ENDED: Final = "ended"
FILE: Final = "file"
"""The three delivery names this source emits, and the translator answers to."""

IDLE: Final = "Done"

START_SCAN: Final = "StartScan"
SCAN_STATUS: Final = "ScanStatus"
FULL_FILE_NAME: Final = "FullFileName"
EXECUTION_ID: Final = "KeeperExecutionId"
STEP_ID: Final = "KeeperStepId"
SCAN_UUID: Final = "ScanUUID"
"""What the engine calls one run.

Upstream has it at 2-BM and 19-BM, and 7-BM carries it in that
beamline's own fork. A station without it serves nothing for this name,
which is why nothing here requires it to answer: the run is reported
either way and only the identifier is missing.
"""

IDENTIFIER_SECONDS: Final = 5.0
"""How long to wait for a new run to be named before giving up on it.

Short, because the identifier is written immediately after the edge, and
because this wait happens while a scan is running rather than while one
is wanted. A station that serves no identifier spends all of it on every
scan and loses nothing but the wait: a tomography scan does not end in
five seconds.
"""

ADDRESS_SECONDS: Final = 30.0
"""How long to wait for a finished scan's address before reporting without one.

Longer than its twin, because this one is written at the end of a
teardown that closes a shutter and moves a sample, rather than
immediately. The cost of the wait is that the next scan's start could be
missed, and the thing that makes that acceptable is that a scan cannot
begin while this record is being written: the start record is still held
open by the scan that is finishing.
"""

REPORT_BY_STATUS: Final[dict[str, Report]] = {
    "scan complete": "Completed",
    "scan aborted": "Aborted",
}
"""What TomoScan says it did, in the keeper's words.

Matched in lower case because the text is written for a screen. Anything
absent from this table is `Failed`, which is the safe direction: a scan
whose ending nobody recognised did not demonstrably work.
"""


def from_tomoscan(
    prefix: str,
    poll_interval: float = 0.5,
    identifier_seconds: float = IDENTIFIER_SECONDS,
    address_seconds: float = ADDRESS_SECONDS,
) -> Iterator[Delivery]:
    """Every scan on one TomoScan server, as it begins and as it finishes.

    Does not end, the way a subscription does not end. The caller stops it.

    The two waits are arguments so a test can drive scans faster than a
    beamline does. A deployment leaves them alone: they are sized by how
    long the engine takes to write a record, which is not something the
    caller knows better than this module does.
    """
    records = {
        suffix: epics.PV(f"{prefix}{suffix}")
        for suffix in (
            START_SCAN,
            SCAN_STATUS,
            FULL_FILE_NAME,
            EXECUTION_ID,
            STEP_ID,
            SCAN_UUID,
        )
    }

    def text(suffix: str) -> str:
        value = records[suffix].get(as_string=True)
        return "" if value is None else str(value)

    def whose() -> dict[str, Any]:
        """The pair that says which step a scan belonged to, read afresh."""
        return {
            "execution_id": text(EXECUTION_ID),
            "step_id": text(STEP_ID),
            "origin": f"{prefix}{START_SCAN}",
        }

    def changed(suffix: str, was: str, limit: float) -> str | None:
        """Wait for a record to stop holding the value it had before.

        The change rather than the content, because both records this is
        used on keep the previous scan's value until the new one lands,
        and one of them is autosaved so it is never empty to begin with.
        Returns what it became, or `None` if it never moved.
        """
        deadline = time.monotonic() + limit
        while True:
            now = text(suffix)
            if now != was:
                return now
            if time.monotonic() >= deadline:
                return None
            time.sleep(poll_interval)

    # Whatever the server is doing when this starts is not a scan this saw
    # begin, so the first transition it acts on is the next one. The two
    # late records are read for the same reason: what they hold now is a
    # baseline to notice movement against, not news.
    was_idle = True
    run_id = text(SCAN_UUID)
    address = text(FULL_FILE_NAME)

    while True:
        idle = text(START_SCAN) == IDLE

        if not idle and was_idle:
            minted = changed(SCAN_UUID, run_id, identifier_seconds)
            run_id = minted if minted is not None else ""
            yield (STARTED, {**whose(), "run_id": run_id})

        if idle and not was_idle:
            written = changed(FULL_FILE_NAME, address, address_seconds)
            if written is not None:
                address = written
            ended: dict[str, Any] = {
                **whose(),
                "status": text(SCAN_STATUS),
                "file": written or "",
                "run_id": run_id,
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
    if name not in (STARTED, ENDED, FILE):
        return Ignored(f"{name} is not a delivery this source emits")

    reference = _reference(record)
    if reference is None:
        if record.get("execution_id") or record.get("step_id"):
            return Unmappable("a scan carrying one keeper id and not the other", origin)
        return Ignored("a scan carrying no keeper ids, so nobody asked for it")

    execution_id, step_id = reference
    if name in (STARTED, ENDED):
        return ReportStepRun(
            execution_id=execution_id,
            step_id=step_id,
            reported="Started" if name == STARTED else _report(str(record.get("status", ""))),
            engine_reference=str(record.get("run_id", "")),
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
    reporter is tied to a particular engine. Holds no state, which is
    the difference from its sibling: the source puts everything a
    delivery means into the delivery, so nothing has to be remembered
    between one and the next.

    What is remembered lives in `from_tomoscan` instead, and it is only
    the previous values of the two records that say what a run was. That
    is a baseline for noticing a change, not an account of a run.
    """

    def handle(name: str, record: Mapping[str, Any]) -> Any:
        return session.act(translate(name, record))

    return handle


__all__ = [
    "ENDED",
    "FILE",
    "REPORT_BY_STATUS",
    "STARTED",
    "from_tomoscan",
    "records_into",
]
