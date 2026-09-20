"""One engine's stream, driven into AROC, one document at a time.

Where the two halves meet: `Translator` says what a document means,
`ArocClient` sends it, and this decides what to do in between and what to
do with a no.

## Shaped for either subscription

`handle` takes one document and returns. It does not own a loop, does not
poll, and does not know whether it was called by a callback the engine
invokes or by something pulling from a queue. That is deliberate: how this
reporter subscribes is undecided, and the two shapes differ in who owns
the loop rather than in what happens to a document.

It also means the checkpoint belongs to the caller. An outcome is a
document this reporter is finished with, so a caller may advance past it;
an exception means the opposite. Nothing here writes a cursor, because
where a cursor lives is the other half of the subscription decision.

## What it remembers, and why none of it matters

Two maps, both caches of things AROC or the stream already knows:

    the translator's    descriptor -> run uid    rebuilt from the stream
    this session's      run uid -> AROC run id   re-read from GET /runs

Kill this process and both come back: the first from the next descriptor,
the second from the external-reference lookup. That is what the two read
slices bought, and it is the difference between a reporter you can
redeploy and one you nurse.

A run's entry is dropped when it ends, so the map tracks live runs rather
than growing for the life of the stream.
"""

from collections.abc import Mapping
from typing import Any, Final
from uuid import UUID

from reporter.client import ArocClient, RequestRefusedError
from reporter.config import ReporterConfig
from reporter.intents import Ignored, ReportRun, Transition, Unmappable, Verb
from reporter.outcomes import Held, Moved, Outcome, Recorded, Skipped, Unchanged
from reporter.translate import ENDING_BY_EXIT_STATUS, Translator

ENDINGS: Final[frozenset[Verb]] = frozenset(ENDING_BY_EXIT_STATUS.values())
"""The verbs after which a run has no more transitions to come.

Used to forget a run rather than to refuse one: AROC decides what may
follow what, and a reporter second-guessing it would refuse a transition
the domain would have accepted.
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
        self._translator = Translator()
        self._run_ids: dict[str, UUID] = {}

    def handle(self, name: str, document: Mapping[str, Any]) -> Outcome:
        """Translate one document and act on what it meant.

        Raises `RequestRefusedError` when AROC's answer was worth
        retrying, and the caller should not advance past the document.
        Any transport failure raises out of the HTTP client unchanged,
        for the same reason.
        """
        intent = self._translator.feed(name, document)
        match intent:
            case Ignored(reason=reason):
                return Skipped(reason)
            case Unmappable(reason=reason, document_name=document_name):
                return Held(reason, document_name)
            case ReportRun():
                return self._report(intent, name)
            case Transition():
                return self._move(intent, name)

    def _report(self, intent: ReportRun, document_name: str) -> Outcome:
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
                document_name,
            )

        try:
            run_id = self._client.report_run(intent, plan_id)
        except RequestRefusedError as refusal:
            return self._held_or_raise(refusal, document_name)

        self._run_ids[intent.external_ref_value] = run_id
        return Recorded(run_id, intent.external_ref_value)

    def _move(self, intent: Transition, document_name: str) -> Outcome:
        """Send a transition, once the engine's run id resolves to AROC's."""
        run_id = self._run_id_for(intent.run_uid)
        if run_id is None:
            return Held(
                f"no run recorded for uid {intent.run_uid}, so its {intent.verb} is lost",
                document_name,
            )

        try:
            self._client.move_run(run_id, intent)
        except RequestRefusedError as refusal:
            if refusal.status == _CONFLICT:
                self._forget(intent)
                return Unchanged(run_id, intent.verb, refusal.detail)
            return self._held_or_raise(refusal, document_name)

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

    def _held_or_raise(self, refusal: RequestRefusedError, document_name: str) -> Outcome:
        """A refusal becomes an outcome, unless waiting could change it."""
        if is_worth_retrying(refusal.status):
            raise refusal
        return Held(f"{refusal.method} {refusal.path} refused: {refusal}", document_name)


__all__ = ["ENDINGS", "Session", "is_worth_retrying"]
