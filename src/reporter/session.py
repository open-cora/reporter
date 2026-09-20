"""One intent at a time, acted on against AROC.

Where the two halves meet: something upstream says what happened, in the
vocabulary of `intents`, and this resolves the ids, sends it, and decides
what to do with a no.

## It does not know which engine it serves

`act` takes an `Intent`, not a document. That boundary was found rather
than designed: it took a document until a second engine turned up with no
documents in it, publishing single values over a control system, and the
only thing coupling this module to the first engine was the signature.

Everything below the translator is the same for both, so the translator is
the caller's to own. A reporter for another engine writes one and reuses
this unchanged. `spikes/tomoscan_adapter/FINDINGS.md` is where that came
from.

## Shaped for either subscription

`act` takes one intent and returns. It does not own a loop, does not
poll, and does not know whether it was called by a callback the engine
invokes or by something pulling from a queue. That is deliberate: how this
reporter subscribes is undecided, and the two shapes differ in who owns
the loop rather than in what happens to a document.

It also means the checkpoint belongs to the caller. An outcome is a
document this reporter is finished with, so a caller may advance past it;
an exception means the opposite. Nothing here writes a cursor, because
where a cursor lives is the other half of the subscription decision.

## What it remembers, and why none of it matters

One map, a cache of something AROC already knows:

    run uid -> AROC run id    re-read from GET /runs

Kill this process and it comes back, from the external-reference lookup.
That is what the read slice bought, and it is the difference between a
reporter you can redeploy and one you nurse. Whatever the translator
remembers is the translator's problem and recovers the same way, from the
stream.

A run's entry is dropped when it ends, so the map tracks live runs rather
than growing for the life of the stream.
"""

from typing import Final
from uuid import UUID

from reporter.client import ArocClient, RequestRefusedError
from reporter.config import ReporterConfig
from reporter.intents import Ignored, Intent, ReportRun, Transition, Unmappable, Verb
from reporter.outcomes import Held, Moved, Outcome, Recorded, Skipped, Unchanged

ENDINGS: Final[frozenset[Verb]] = frozenset({"complete", "abort", "fail"})
"""The verbs after which a run has no more transitions to come.

Used to forget a run rather than to refuse one: AROC decides what may
follow what, and a reporter second-guessing it would refuse a transition
the domain would have accepted.

Written out rather than derived from one engine's exit statuses, which is
what it used to be. Which verbs are terminal is AROC's fact, and reading
it off a translator made it look like the engine's.
"""

_CONFLICT: Final = 409
_TOO_MANY: Final = 429


def is_worth_retrying(status: int) -> bool:
    """Whether sending the same request again could plausibly work.

    A 5xx is AROC or something in front of it having a bad moment, and a
    429 is being asked to slow down; both change on their own. Every
    other refusal is about the request, and the request will be identical
    next time.

    The split decides whether a document becomes an outcome the caller
    can advance past, or an exception telling it not to.
    """
    return status >= 500 or status == _TOO_MANY


class Session:
    """Holds one stream's translator and its resolved run ids."""

    def __init__(self, client: ArocClient, config: ReporterConfig) -> None:
        self._client = client
        self._config = config
        self._run_ids: dict[str, UUID] = {}

    def act(self, intent: Intent) -> Outcome:
        """Do whatever one intent asks for, and say what came of it.

        Raises `RequestRefusedError` when AROC's answer was worth
        retrying, and the caller should not advance past the intent. Any
        transport failure raises out of the HTTP client unchanged, for
        the same reason.
        """
        match intent:
            case Ignored(reason=reason):
                return Skipped(reason)
            case Unmappable(reason=reason, origin=origin):
                return Held(reason, origin)
            case ReportRun():
                return self._report(intent)
            case Transition():
                return self._move(intent)

    def _report(self, intent: ReportRun) -> Outcome:
        """Send a run, once its plan name resolves to a plan this holds.

        A name with no entry is refused rather than authored. A start
        document describes one invocation and carries nothing a correct
        parameter schema could be derived from, so a reporter that
        authored a plan here would be inventing a constraint and every
        later run would cite it.
        """
        plan_id = self._config.plan_id_for(intent.plan_name)
        if plan_id is None:
            return Held(
                f"no plan configured for {intent.plan_name!r}, so this run is not recorded",
                intent.origin,
            )

        try:
            run_id = self._client.report_run(intent, plan_id)
        except RequestRefusedError as refusal:
            return self._held_or_raise(refusal, intent.origin)

        self._run_ids[intent.external_ref_value] = run_id
        return Recorded(run_id, intent.external_ref_value)

    def _move(self, intent: Transition) -> Outcome:
        """Send a transition, once the engine's run id resolves to AROC's."""
        run_id = self._run_id_for(intent.run_uid)
        if run_id is None:
            return Held(
                f"no run recorded for uid {intent.run_uid}, so its {intent.verb} is lost",
                intent.origin,
            )

        try:
            self._client.move_run(run_id, intent)
        except RequestRefusedError as refusal:
            if refusal.status == _CONFLICT:
                self._forget(intent)
                return Unchanged(run_id, intent.verb, refusal.detail)
            return self._held_or_raise(refusal, intent.origin)

        self._forget(intent)
        return Moved(run_id, intent.verb)

    def _run_id_for(self, run_uid: str) -> UUID | None:
        """AROC's id for an engine run: from memory, then from AROC.

        The second line is the whole of what a restart needs. Before
        `GET /runs` took an external-reference filter there was no second
        line, and a uid this process had forgotten was a run nothing
        could reach again.
        """
        remembered = self._run_ids.get(run_uid)
        if remembered is not None:
            return remembered

        found = self._client.find_run(run_uid)
        if found is not None:
            self._run_ids[run_uid] = found
        return found

    def _forget(self, intent: Transition) -> None:
        """Drop a run once it has ended, so the map tracks live runs."""
        if intent.verb in ENDINGS:
            self._run_ids.pop(intent.run_uid, None)

    def _held_or_raise(self, refusal: RequestRefusedError, origin: str) -> Outcome:
        """A refusal becomes an outcome, unless waiting could change it."""
        if is_worth_retrying(refusal.status):
            raise refusal
        return Held(f"{refusal.method} {refusal.path} refused: {refusal}", origin)


__all__ = ["ENDINGS", "Session", "is_worth_retrying"]
