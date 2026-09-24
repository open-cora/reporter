"""One intent at a time, acted on against AROC.

Where the two halves meet: something upstream says what happened, in the
vocabulary of `intents`, and this sends it and decides what to do with a
no.

## Two bounded contexts, one session

It reports into Execution, what an engine did to one step's run, and into
Custody, where the data that step produced is being kept. The second is
optional: no store lookup means no dataset leg and everything else
unchanged.

The two are in one session rather than two because they name the same
step. A dataset cites the acquisition that produced it, which is exactly
the acquisition the report is about, so the delivery that ends a run is
the delivery that knows where to ask about its data.

## It remembers nothing

This module used to hold a map from an engine's run uid to AROC's run id,
with a lookup behind it for what a restart had forgotten. Both are gone.
The ids are on the intent, because whatever dispatched the work carried
them into the engine's own metadata and the translator reads them back
out, so there is nothing here to cache and nothing to recover.

What was lost with them is written down in `translate`: the translator
holds the reference from a start to a stop, and a restart mid-scan cannot
get it back, where the old lookup could. That is a gap in the layer that
holds the state rather than one this module papers over.

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
the loop rather than in what happens to a delivery.

It also means the checkpoint belongs to the caller. An outcome is a
delivery this reporter is finished with, so a caller may advance past it;
an exception means the opposite. Nothing here writes a cursor, because
where a cursor lives is the other half of the subscription decision.
"""

from typing import Final

from reporter.client import ArocClient, RequestRefusedError
from reporter.config import ReporterConfig
from reporter.intents import (
    Ignored,
    Intent,
    RegisterDataset,
    Report,
    ReportStepRun,
    Unmappable,
)
from reporter.outcomes import Held, Kept, Outcome, Relayed, Skipped, Unchanged
from reporter.stores import StoreLookup, StoreRefusedError

ENDINGS: Final[frozenset[Report]] = frozenset({"Completed", "Aborted", "Failed"})
"""The reports after which an engine has nothing further to say about a run.

Used to ask a store for the data rather than to refuse a report: AROC
decides what may follow what, and a reporter second-guessing it would
withhold a report the domain would have accepted.

Written out rather than derived from one engine's exit statuses, which is
what it used to be. Which reports are terminal is AROC's fact, and
reading it off a translator made it look like the engine's.
"""

_CONFLICT: Final = 409
_TOO_MANY: Final = 429


def is_worth_retrying(status: int) -> bool:
    """Whether sending the same request again could plausibly work.

    A 5xx is AROC or something in front of it having a bad moment, and a
    429 is being asked to slow down; both change on their own. Every
    other refusal is about the request, and the request will be identical
    next time.

    The split decides whether a delivery becomes an outcome the caller
    can advance past, or an exception telling it not to.
    """
    return status >= 500 or status == _TOO_MANY


class Session:
    """Sends one stream's intents, and asks the store when there is one."""

    def __init__(
        self,
        client: ArocClient,
        config: ReporterConfig,
        store: StoreLookup | None = None,
    ) -> None:
        if store is not None and config.store is None:
            raise ValueError(
                "A store lookup needs a [store] table in the configuration, which is "
                "where the scheme its addresses belong to is written down."
            )
        self._client = client
        self._config = config
        self._store = store

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
            case ReportStepRun():
                return self._relay(intent)
            case RegisterDataset():
                return self._register(intent)

    def _relay(self, intent: ReportStepRun) -> Outcome:
        """Send one engine report, and file what it produced if it ended one."""
        declined: str | None = None
        try:
            self._client.report_step_run(intent)
        except RequestRefusedError as refusal:
            if refusal.status != _CONFLICT:
                return self._held_or_raise(refusal, intent.origin)
            declined = refusal.detail

        kept = self._keep(intent)
        if kept is not None:
            return kept
        if declined is not None:
            return Unchanged(intent.execution_id, intent.step_id, intent.reported, declined)
        return Relayed(intent.execution_id, intent.step_id, intent.reported)

    def _keep(self, intent: ReportStepRun) -> Outcome | None:
        """Register what an ended run produced, if a store says where it is.

        `None` means there was nothing to do and the caller should report
        the relay on its own: either this deployment has no store, or the
        run has not ended and so has produced nothing to speak of yet.

        It runs after a declined report as well as an accepted one, and
        that is not an oversight. A 409 is what a redelivery looks like,
        and the delivery it repeats may have recorded the ending and died
        before recording the data. Re-registering an address AROC already
        holds costs one request and returns the same id, because the retry
        key is derived from that address.

        The store is asked about the engine's own run id, which is why
        that travels on every report rather than only on a start. A store
        watching an engine files under the engine's names.

        This is the fast path: the delivery that ended the run is what
        prompts the question, so the answer is filed in the same breath.
        The slow path is `_register`, reached through `act` by anything
        that found the data some other way.
        """
        if self._store is None or self._config.store is None or intent.reported not in ENDINGS:
            return None

        try:
            location = self._store.locate(intent.engine_reference)
        except StoreRefusedError as refusal:
            if is_worth_retrying(refusal.status):
                raise
            return Held(f"the store refused: {refusal}", intent.origin)

        if location is None:
            return Held(
                f"the store holds nothing for run {intent.engine_reference}, so its "
                f"{intent.reported.lower()} is recorded and what it produced is not",
                intent.origin,
            )

        return self._file(
            RegisterDataset(
                execution_id=intent.execution_id,
                step_id=intent.step_id,
                external_ref_value=location.path,
                occurred_at=location.occurred_at,
                origin=intent.origin,
            ),
            reported=intent.reported,
        )

    def _register(self, intent: RegisterDataset) -> Outcome:
        """File a dataset somebody else went and found.

        The other way in, and the one that makes `intents` a complete
        description of this reporter rather than most of one. Whatever
        produced this intent did the asking: a sweep of a store, a
        backfill, a repair by hand.

        There is no report because no engine report arrived with it,
        which is exactly the difference from the fast path above. It also
        does not resolve anything any more: an intent arriving this way
        carries the same two ids the fast path has, because a caller that
        cannot name the acquisition has nothing to file against.
        """
        return self._file(intent, reported=None)

    def _file(self, intent: RegisterDataset, *, reported: Report | None) -> Outcome:
        """The one request both ways in make, and the one outcome."""
        if self._config.store is None:
            return Held(
                "a dataset was reported and no [store] table says what scheme its "
                "address belongs to",
                intent.origin,
            )

        try:
            dataset_id = self._client.register_dataset(
                intent, scheme=self._config.store.external_ref_scheme
            )
        except RequestRefusedError as refusal:
            return self._held_or_raise(refusal, intent.origin)

        return Kept(
            intent.execution_id,
            intent.step_id,
            reported,
            dataset_id,
            intent.external_ref_value,
        )

    def _held_or_raise(self, refusal: RequestRefusedError, origin: str) -> Outcome:
        """A refusal becomes an outcome, unless waiting could change it."""
        if is_worth_retrying(refusal.status):
            raise refusal
        return Held(f"{refusal.method} {refusal.path} refused: {refusal}", origin)


__all__ = ["ENDINGS", "Session", "is_worth_retrying"]
