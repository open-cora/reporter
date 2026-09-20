"""Turn an engine's documents into intents, and nothing else.

The functional core. No network, no clock, no configuration: documents in,
`Intent` values out. That is what lets every result the spike obtained by
driving a real engine be re-asserted here against the captured file, with
no engine and no AROC running.

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

The state is bounded: a run's descriptors are forgotten when its `stop`
arrives. It is still a pure core, because what it holds is knowledge the
stream has already delivered rather than anything read from outside.

## Joining a stream late is quiet, on purpose

A reporter that starts mid-run sees events for descriptors it never saw.
Interruption is checked before the run is resolved, so ordinary data
events from before the join are `Ignored` and only an unattributable
interruption is loud. The alternative reports every reading as a problem
and teaches whoever is watching to stop reading the output.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Final, cast

from reporter.intents import Ignored, Intent, ReportRun, Transition, Unmappable, Verb

ENDING_BY_EXIT_STATUS: Final[dict[str, Verb]] = {
    "success": "complete",
    "abort": "abort",
    "fail": "fail",
}
"""Three exit statuses onto three endings, and one trap worth knowing.

Asking an engine to stop early and a plan running to completion both
record `success`, and the harder stop records `abort`. So which method a
person called is not recoverable from a document, and a run that somebody
halted deliberately is indistinguishable here from one that ran out. The
spike established this by driving all three and comparing; it is a fact
about the wire rather than a choice made here.
"""

VERB_BY_INTERRUPTION: Final[dict[str, Verb]] = {"pause": "pause", "resume": "resume"}
"""The interruption channel, which is the shakiest of the three signals.

Endings arrive on a document type whose whole purpose is to announce one.
Pause and resume arrive as a reading inside an ordinary data event, on a
channel the engine's own documentation calls experimental. Treat a gap
here as likelier than a gap in the endings.
"""

_INTERRUPTION_KEY: Final = "interruption"

_SCALARS: Final = (bool, int, float, str)


def engine_instant(document: Mapping[str, Any]) -> datetime | None:
    """A document's own `time`, as an instant AROC will accept.

    Documents are stamped in UNIX seconds. AROC refuses a timestamp with
    no offset, so UTC is named rather than left to whatever zone the
    reporter happens to run in.

    `None` when the document carries no usable time, which the six run
    write commands accept: AROC then stamps the moment it was told, and
    the record says so rather than inventing a moment it was not there
    for.
    """
    seconds = document.get("time")
    if not isinstance(seconds, (int, float)) or isinstance(seconds, bool):
        return None
    return datetime.fromtimestamp(float(seconds), tz=UTC)


def idempotency_key_for(external_ref_value: str) -> str:
    """The key that makes a redelivered start harmless.

    Derived rather than remembered, which is the whole point. AROC's store
    keys on `(principal_id, key, surface_id)`, so a reporter running as
    one actor recomputes this after any restart having persisted nothing,
    and the second delivery of a start returns the first one's run id
    instead of minting a second record.

    Prefixed because a bare uid in that table says nothing about what it
    was for, and somebody will eventually read the table.
    """
    return f"report-run:{external_ref_value}"


def _parameters(start: Mapping[str, Any]) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Compose a run's parameters, and name what was left out.

    Scalars come from the arguments the call was made with. Device names
    come from a different key, because the argument list holds reprs:
    whole object dumps with configuration inline, which would go verbatim
    into a log nobody can edit.
    """
    arguments: Mapping[str, Any] = start.get("plan_args") or {}
    parameters: dict[str, Any] = {
        key: value for key, value in arguments.items() if isinstance(value, _SCALARS)
    }
    dropped = tuple(sorted(set(arguments) - set(parameters)))

    detectors = start.get("detectors")
    if isinstance(detectors, list):
        parameters["detectors"] = [str(name) for name in cast("list[Any]", detectors)]

    return parameters, dropped


class Translator:
    """One engine's document stream, turned into intents one document at a time.

    Hold one per stream. Feeding two engines' documents to a single
    instance is safe as far as attribution goes, since descriptors and
    runs are keyed by uid and those are globally unique, but the run map
    then grows with both and nothing here says which engine a run came
    from. One per stream keeps that question from arising.
    """

    def __init__(self) -> None:
        self._run_by_descriptor: dict[str, str] = {}

    def feed(self, name: str, document: Mapping[str, Any]) -> Intent:
        """Translate one document, in the order the stream delivered it.

        Order matters for `event` documents only, and only because a
        descriptor has to have arrived first. Everything else is
        self-contained.
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
        plan_name = document.get("plan_name")
        if not isinstance(uid, str) or not isinstance(plan_name, str):
            return Unmappable("a start carries no uid or no plan_name", "start")

        parameters, dropped = _parameters(document)
        return ReportRun(
            plan_name=plan_name,
            parameters=parameters,
            external_ref_value=uid,
            occurred_at=engine_instant(document),
            origin="start",
            dropped=dropped,
        )

    def _descriptor(self, document: Mapping[str, Any]) -> Intent:
        """Index a descriptor against its run. Nothing is sent for one.

        This is the only reason descriptors are read at all, and it is why
        a translator that skips them cannot attribute a pause.
        """
        uid = document.get("uid")
        run_uid = document.get("run_start")
        if isinstance(uid, str) and isinstance(run_uid, str):
            self._run_by_descriptor[uid] = run_uid
        return Ignored("a descriptor says what a stream will carry, not what a run did")

    def _event(self, document: Mapping[str, Any]) -> Intent:
        data: Mapping[str, Any] = document.get("data") or {}
        verb = VERB_BY_INTERRUPTION.get(str(data.get(_INTERRUPTION_KEY)))
        if verb is None:
            return Ignored("an event carrying no interruption is a reading")

        descriptor = document.get("descriptor")
        run_uid = self._run_by_descriptor.get(str(descriptor))
        if run_uid is None:
            return Unmappable(
                f"an interruption on descriptor {descriptor} names no run this "
                "stream has introduced, so it cannot be attributed",
                "event",
            )
        return Transition(
            run_uid=run_uid, verb=verb, occurred_at=engine_instant(document), origin="event"
        )

    def _stop(self, document: Mapping[str, Any]) -> Intent:
        run_uid = document.get("run_start")
        if not isinstance(run_uid, str):
            return Unmappable("a stop carries no run_start", "stop")

        verb = ENDING_BY_EXIT_STATUS.get(str(document.get("exit_status")))
        if verb is None:
            return Unmappable(
                f"exit_status {document.get('exit_status')!r} maps to no ending", "stop"
            )

        self._forget(run_uid)
        return Transition(
            run_uid=run_uid, verb=verb, occurred_at=engine_instant(document), origin="stop"
        )

    def _forget(self, run_uid: str) -> None:
        """Drop a finished run's descriptors, so the map tracks live runs.

        Without this the map is a leak on a stream that never ends. An
        event arriving after its run's stop then reads as unattributable,
        which is what it is.
        """
        self._run_by_descriptor = {
            descriptor: run for descriptor, run in self._run_by_descriptor.items() if run != run_uid
        }


__all__ = [
    "ENDING_BY_EXIT_STATUS",
    "VERB_BY_INTERRUPTION",
    "Translator",
    "engine_instant",
    "idempotency_key_for",
]
