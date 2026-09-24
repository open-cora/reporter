"""Turn an engine's documents into intents, and nothing else.

The functional core. No network, no clock, no configuration: documents in,
`Intent` values out. That is what lets every result the spike obtained by
driving a real engine be re-asserted here against the captured file, with
no engine and no AROC running.

## Where the AROC reference comes from

Whatever drives an execution hands one acquisition step to an engine and
carries that step's AROC ids into the engine's own metadata. A start
document is where they arrive, under `AROC_METADATA_KEYS` below, and this
is the only place in the reporter that knows the spelling.

That is an outward-facing identifier in somebody else's records, which is
a thing this tree had not done before and which was weighed rather than
assumed: the alternative was for the reporter to resolve a run by an
external reference through a read slice, which is what the previous
design did and which cost a lookup, a configured scheme, and a class of
mistake where two records answered to one reference. Under a dispatch the
ids exist before the engine is asked for anything, so putting them in the
metadata is the cheaper half of a trade that used to go the other way.

**Nothing in this repository writes those keys yet.** The conductor's
recording seam is the place they will be written and it is not built, so
this side of the contract is stated here and unenforced. A capture taken
before that lands produces `Ignored` for every document in it, which is
the behaviour the section below describes rather than a failure.

## Work AROC never dispatched is quiet

A document carrying no AROC reference belongs to something somebody ran
by hand at the beamline. It is real work and this system has nothing to
record it against: there is no execution, no step, and no way to make one
from a document. So it is `Ignored` rather than `Unmappable`.

That is a deliberate loss and a reversible one. Nothing is destroyed, the
engine keeps its own record, and a reported shape could be added later as
a purely additive change. Making it an alert instead would fire on every
document of every hand-run scan, which teaches whoever is watching to
stop reading the output, and this reporter's whole `Held` channel rests
on that not happening.

## Why this holds state

An `event` document does not say which run it belongs to. It names a
descriptor, and only the `descriptor` document carries `run_start`:

    start       uid ------------------+
    descriptor  uid, run_start -------+--> descriptor uid -> run uid
    event       descriptor -----------+
    stop        run_start

So attributing an event is a two-hop lookup, and the stream supplies both
hops. The spike sidestepped it by tracking "the run we are currently
walking", which held only because it replayed one scenario at a time. A
live stream makes no such promise.

There is now a second map, and it is the one that matters more. Only the
start carries the AROC reference, and every later document about that run
carries the engine's uid instead, so what the start said has to be
remembered from the start to the stop. It records `None` for a run that
is not this system's, because that answer has to last the run too.

Both maps are bounded: a run's descriptors and whatever its start said
are forgotten when its `stop` arrives.

**Restarting loses the references for runs in flight.** The old design
recovered from AROC, because a run could be found by its external
reference; a step cannot, because AROC publishes no lookup from an
engine's reference to the step that opened it. So a reporter restarted
mid-scan reports nothing further about that scan, and says so as `Held`
on each document rather than silently. Closing it needs a query AROC does
not have, and is not worth building before something is actually driving
these streams.

## Joining a stream late is loud, and that is the change

A reporter that starts mid-run sees documents for a run whose start it
never saw, so it has no entry for them at all. That used to be quiet,
because the run could be resolved from AROC afterwards. It cannot be now,
so an interruption or an ending for a run this stream never introduced is
`Unmappable`: it may be a report this system asked for and will not get.

It may equally be a hand-run scan that started before this process did,
and nothing can tell the two apart. Being loud about the pair is the
choice here, because the case that matters is the one where a report is
genuinely lost, and it costs a handful of alerts once per restart rather
than a stream of them for the life of a scan.

Ordinary data events stay quiet, because they were never going anywhere.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

from reporter.intents import Ignored, Intent, Report, ReportStepRun, Unmappable

AROC_METADATA_KEYS: Final[tuple[str, str]] = ("aroc_execution_id", "aroc_step_id")
"""The two keys a driver writes into an engine's metadata, in order.

Prefixed, because they sit in a namespace this system does not own and a
bare `step_id` in somebody else's start document says nothing about whose
step it is.

Read off the top level of the start document rather than out of a nested
table. Which nested key an engine offers for caller metadata differs
between engines and between versions of one engine, and the top level is
the one place every engine this has been driven against puts what it was
given.
"""

ENDING_BY_EXIT_STATUS: Final[dict[str, Report]] = {
    "success": "Completed",
    "abort": "Aborted",
    "fail": "Failed",
}
"""Three exit statuses onto three endings, and one trap worth knowing.

Asking an engine to stop early and a plan running to completion both
record `success`, and the harder stop records `abort`. So which method a
person called is not recoverable from a document, and a run that somebody
halted deliberately is indistinguishable here from one that ran out. The
spike established this by driving all three and comparing; it is a fact
about the wire rather than a choice made here.
"""

REPORT_BY_INTERRUPTION: Final[dict[str, Report]] = {"pause": "Paused", "resume": "Resumed"}
"""The interruption channel, which is the shakiest of the three signals.

Endings arrive on a document type whose whole purpose is to announce one.
Pause and resume arrive as a reading inside an ordinary data event, on a
channel the engine's own documentation calls experimental. Treat a gap
here as likelier than a gap in the endings.
"""

_INTERRUPTION_KEY: Final = "interruption"


def engine_instant(document: Mapping[str, Any]) -> datetime | None:
    """A document's own `time`, as an instant AROC will accept.

    Documents are stamped in UNIX seconds. AROC refuses a timestamp with
    no offset, so UTC is named rather than left to whatever zone the
    reporter happens to run in.

    `None` when the document carries no usable time, which the report
    command accepts: AROC then stamps the moment it was told, and the
    record says so rather than inventing a moment it was not there for.
    """
    seconds = document.get("time")
    if not isinstance(seconds, (int, float)) or isinstance(seconds, bool):
        return None
    return datetime.fromtimestamp(float(seconds), tz=UTC)


def aroc_reference(document: Mapping[str, Any]) -> tuple[UUID, UUID] | None:
    """The execution and step a start document says it belongs to.

    `None` when either key is absent, which is a hand-run scan, and also
    when either is present and is not a UUID, which is not. The two are
    not told apart here and the caller treats both as work this system
    did not dispatch.

    That is a deliberate narrowing of an alert rather than an oversight.
    A malformed reference means whatever wrote it is broken, which is
    worth knowing, and there is no way to tell it from a key an unrelated
    engine happens to use for something else. Quiet is the reversible
    direction; the loud one cannot be taken back once it has trained
    somebody to ignore the channel.
    """
    execution_key, step_key = AROC_METADATA_KEYS
    raw_execution = document.get(execution_key)
    raw_step = document.get(step_key)
    if not isinstance(raw_execution, str) or not isinstance(raw_step, str):
        return None
    try:
        return UUID(raw_execution), UUID(raw_step)
    except ValueError:
        return None


class Translator:
    """One engine's document stream, turned into intents one document at a time.

    Hold one per stream. Feeding two engines' documents to a single
    instance is safe as far as attribution goes, since descriptors and
    runs are keyed by uid and those are globally unique, but the maps
    then grow with both and nothing here says which engine a run came
    from. One per stream keeps that question from arising.
    """

    def __init__(self) -> None:
        self._run_by_descriptor: dict[str, str] = {}
        self._reference_by_run: dict[str, tuple[UUID, UUID] | None] = {}

    def feed(self, name: str, document: Mapping[str, Any]) -> Intent:
        """Translate one document, in the order the stream delivered it.

        Order matters for two reasons now. An `event` needs its
        descriptor to have arrived, and everything after a start needs
        that start, because the start is the only document carrying the
        AROC reference.
        """
        if name == "start":
            return self._start(document)
        if name == "descriptor":
            return self._descriptor(document)
        if name == "event":
            return self._event(document)
        if name == "stop":
            return self._stop(document)
        return Ignored(f"no rule for a {name} document")

    def _start(self, document: Mapping[str, Any]) -> Intent:
        uid = document.get("uid")
        if not isinstance(uid, str):
            return Unmappable("a start carries no uid", "start")

        reference = aroc_reference(document)
        self._reference_by_run[uid] = reference
        if reference is None:
            return Ignored(
                f"run {uid} carries no AROC reference, so it is work this system did not dispatch"
            )

        execution_id, step_id = reference
        return ReportStepRun(
            execution_id=execution_id,
            step_id=step_id,
            reported="Started",
            engine_reference=uid,
            occurred_at=engine_instant(document),
            origin="start",
        )

    def _descriptor(self, document: Mapping[str, Any]) -> Intent:
        """Index a descriptor against its run. Nothing is sent for one.

        This is the only reason descriptors are read at all, and it is why
        a translator that skips them cannot attribute a pause.

        Indexed whether or not the run is one AROC dispatched, because
        deciding that means a lookup this arm would have to do on every
        descriptor to save a dictionary entry on some of them.
        """
        uid = document.get("uid")
        run_uid = document.get("run_start")
        if isinstance(uid, str) and isinstance(run_uid, str):
            self._run_by_descriptor[uid] = run_uid
        return Ignored("a descriptor says what a stream will carry, not what a run did")

    def _event(self, document: Mapping[str, Any]) -> Intent:
        data: Mapping[str, Any] = document.get("data") or {}
        reported = REPORT_BY_INTERRUPTION.get(str(data.get(_INTERRUPTION_KEY)))
        if reported is None:
            return Ignored("an event carrying no interruption is a reading")

        descriptor = document.get("descriptor")
        run_uid = self._run_by_descriptor.get(str(descriptor))
        if run_uid is None:
            return Unmappable(
                f"an interruption on descriptor {descriptor} names no run this "
                "stream has introduced, so it cannot be attributed",
                "event",
            )
        return self._about(run_uid, reported, document, origin="event")

    def _stop(self, document: Mapping[str, Any]) -> Intent:
        run_uid = document.get("run_start")
        if not isinstance(run_uid, str):
            return Unmappable("a stop carries no run_start", "stop")

        reported = ENDING_BY_EXIT_STATUS.get(str(document.get("exit_status")))
        if reported is None:
            return Unmappable(
                f"exit_status {document.get('exit_status')!r} maps to no ending", "stop"
            )

        intent = self._about(run_uid, reported, document, origin="stop")
        self._forget(run_uid)
        return intent

    def _about(
        self,
        run_uid: str,
        reported: Report,
        document: Mapping[str, Any],
        *,
        origin: str,
    ) -> Intent:
        """Build a report for a run whose start this stream carried.

        Three cases, and the map tells them apart by holding a reference,
        holding `None`, or holding nothing.

        A reference is the ordinary path. `None` means this stream
        carried the start and it named no execution, so the run is
        somebody's hand-run scan and every document of it stays as quiet
        as the start was. Nothing at all means this stream never carried
        the start, which is the restart case, and that is the one worth
        an alert: a report this system may have asked for is being lost
        and no lookup will recover it.
        """
        if run_uid not in self._reference_by_run:
            return Unmappable(
                f"run {run_uid} has no AROC reference on this stream, so its "
                f"{reported.lower()} cannot be reported: this reporter joined "
                "after its start, or the run is not one AROC dispatched",
                origin,
            )
        reference = self._reference_by_run[run_uid]
        if reference is None:
            return Ignored(
                f"run {run_uid} started without an AROC reference, so its "
                f"{reported.lower()} is not this system's to record"
            )
        execution_id, step_id = reference
        return ReportStepRun(
            execution_id=execution_id,
            step_id=step_id,
            reported=reported,
            engine_reference=run_uid,
            occurred_at=engine_instant(document),
            origin=origin,
        )

    def _forget(self, run_uid: str) -> None:
        """Drop a finished run, so the maps track live runs.

        Without this they are a leak on a stream that never ends. A
        document arriving after its run's stop then reads as
        unattributable, which is what it is.
        """
        self._reference_by_run.pop(run_uid, None)
        self._run_by_descriptor = {
            descriptor: run for descriptor, run in self._run_by_descriptor.items() if run != run_uid
        }


__all__ = [
    "AROC_METADATA_KEYS",
    "ENDING_BY_EXIT_STATUS",
    "REPORT_BY_INTERRUPTION",
    "Translator",
    "aroc_reference",
    "engine_instant",
]
