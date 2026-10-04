"""One intent at a time, acted on against whatever was wired in.

Where the two halves meet: something upstream says what happened, in the
vocabulary of `intents`, and this acts on it and decides what to do with
a no.

## Two bounded contexts, one session

It reports into Execution, what an engine did to one step's run, and
into Custody, where the data that step produced is being kept and what
is inside it. The second is optional: no `Filing` and no `Locating`
means no dataset leg and everything else unchanged, and no `Describing`
means the leg runs and says nothing about contents.

The two are in one session rather than two because they name the same
step. A dataset cites the run that produced it, which is exactly the run
the report is about, so the delivery that ends a run is the delivery
that knows where to ask about its data.

## It is given capabilities, not a client and a configuration

Five seams in, and which service answers them is a question this file
cannot ask. It used to take one client object and the whole
configuration, and that configuration was consulted at three separate
places to work out whether the dataset leg was on. A session that cannot file is now a
session that was not given `Filing`, so there is one answer and nothing
to disagree with itself.

It also removed a state that should never have been reachable. A store
lookup with no store table was a constructor argument pair this had to
reject at runtime, and the two are now built together or not at all.

## It remembers nothing

This module used to hold a map from an engine's own reference for a run
to the record the keeper then held for it, with a lookup behind it for
what a restart had forgotten. Both are gone. The ids are on the intent,
because whatever dispatched the work carried them into the engine's own
metadata and the translator reads them back out, so there is nothing
here to cache and nothing to recover.

## It does not know which engine it serves

`act` takes an `Intent`, not a document. That boundary was found rather
than designed: it took a document until a second engine turned up with
no documents in it, publishing single values over a control system, and
the only thing coupling this module to the first engine was the
signature.

## Shaped for either subscription

`act` takes one intent and returns. It does not own a loop, does not
poll, and does not know whether it was called by a callback the engine
invokes or by something pulling from a queue.

It also means the checkpoint belongs to the caller. An outcome is a
delivery this reporter is finished with, so a caller may advance past
it; `UnavailableError` means the opposite.
"""

from typing import Final
from uuid import UUID

from reporter.intents import (
    Ignored,
    Intent,
    RegisterDataset,
    Report,
    ReportStepRun,
    Unmappable,
)
from reporter.outcomes import Held, Kept, Outcome, Relayed, Skipped, Unchanged
from reporter.seams import (
    Cataloguing,
    Describing,
    DisagreedError,
    Filing,
    Locating,
    RefusedError,
    Reporting,
)

ENDINGS: Final[frozenset[Report]] = frozenset({"Completed", "Aborted", "Failed"})
"""The three reports that mean a run is over and its data is worth asking about.

A store is asked once per run rather than once per delivery, and this is
which delivery does the asking.
"""


class Session:
    """Sends one stream's intents, and asks a store when there is one."""

    def __init__(
        self,
        reporting: Reporting,
        filing: Filing | None = None,
        locating: Locating | None = None,
        describing: Describing | None = None,
        cataloguing: Cataloguing | None = None,
    ) -> None:
        if (describing is None) != (cataloguing is None):
            raise ValueError(
                "Describing and Cataloguing are given together or not at all. Half the "
                "pair is the quietest way to be misconfigured: the describer is never "
                "called, the outcome carries no reason, and the deployment reads as one "
                "that was never asked to describe anything."
            )
        self._reporting = reporting
        self._filing = filing
        self._locating = locating
        self._describing = describing
        self._cataloguing = cataloguing

    def act(self, intent: Intent) -> Outcome:
        """Do whatever one intent asks for, and say what came of it.

        Raises `UnavailableError` when nothing answered and asking again
        might, in which case the caller should not advance past the
        intent. Everything else is an outcome, and an outcome means this
        delivery is finished with.
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
            self._reporting.record(intent)
        except DisagreedError as disagreement:
            declined = disagreement.detail
        except RefusedError as refusal:
            return Held(f"the report was refused: {refusal}", intent.origin)

        kept = self._keep(intent)
        if kept is not None:
            return kept
        if declined is not None:
            return Unchanged(intent.execution_id, intent.step_id, intent.reported, declined)
        return Relayed(intent.execution_id, intent.step_id, intent.reported)

    def _keep(self, intent: ReportStepRun) -> Outcome | None:
        """Register what an ended run produced, if a store says where it is.

        `None` means there was nothing to do and the caller should report
        the relay on its own: either this deployment cannot locate data,
        or the run has not ended and so has produced nothing to speak of
        yet.

        It runs after a disagreement as well as after an accepted report,
        and that is not an oversight. A disagreement is what a redelivery
        looks like, and the delivery it repeats may have recorded the
        ending and died before recording the data. Re-filing an address
        the keeper already holds costs one request and returns the same
        id, because the far side is asked to make that the case.

        The store is asked about the engine's own run id, which is why
        that travels on every report rather than only on a start. A store
        watching an engine files under the engine's names.

        This is the fast path: the delivery that ended the run is what
        prompts the question, so the answer is filed in the same breath.
        The slow path is `_register`, reached through `act` by anything
        that found the data some other way.
        """
        if self._locating is None or intent.reported not in ENDINGS:
            return None

        try:
            location = self._locating.locate(intent.engine_reference)
        except RefusedError as refusal:
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
        which is exactly the difference from the fast path above.
        """
        return self._file(intent, reported=None)

    def _file(self, intent: RegisterDataset, *, reported: Report | None) -> Outcome:
        """The one call both ways in make, and the one outcome."""
        if self._filing is None:
            return Held(
                "a dataset was reported and this reporter was given nothing to file it "
                "with, so nothing records where the data is",
                intent.origin,
            )

        try:
            dataset_id = self._filing.record(intent)
        except RefusedError as refusal:
            return Held(f"the dataset was refused: {refusal}", intent.origin)

        return Kept(
            intent.execution_id,
            intent.step_id,
            reported,
            dataset_id,
            intent.external_ref_value,
            self._describe(dataset_id, intent.external_ref_value),
        )

    def _describe(self, dataset_id: UUID, address: str) -> str | None:
        """Ask what is inside the data, and tell the record, risking neither.

        Returns why nothing was recorded, or `None` when a description
        landed and when this deployment describes nothing. Runs after
        filing rather than instead of it, because it needs the id filing
        returns and because a record of where the data is must not
        depend on anything being able to read it.

        ## Why this asks now

        The delivery that ends a run is the delivery that knows the work
        is over, and the end of the work is the trigger a description
        wants: a file being closed is not the same moment. A scan engine
        at some beamlines reopens its finished file to append the
        rotation angle of each frame, and a description taken before
        that reports angles that are missing, which is also what the
        real failure looks like.

        For the engine watched over records, that gap is closed, and it
        was read off the engine rather than assumed. The ending here is
        the busy record returning to its idle value, the engine puts
        that record back inside the base routine that ends a scan, and
        every station that appends angles does so before calling it. The
        address this then waits on is written later still.

        It is a property of that engine and not of this code, so a
        second engine has to be checked rather than inherited. What
        makes an early look survivable either way is that a later
        description is an ordinary later fact on the far side, so it
        costs a row rather than the truth.

        ## Why nothing here escapes

        Every failure becomes a reason on the outcome, including the
        kind that would otherwise mean "ask again". Letting one
        propagate would retry the whole delivery, so a file nothing can
        open would re-send a report and re-file an address that both
        landed the first time, and then report the delivery held, which
        hides a leg that worked behind one that is optional.

        The catch is wide and its scope is one pair of calls. The seams
        promise three classes and a describer reaching into a format
        library is the most likely place in this package for a fourth
        to arrive. One escaping here would kill the relay's worker, and
        a reporter whose worker has died looks exactly like a beamline
        that is not running.
        """
        if self._describing is None or self._cataloguing is None:
            return None
        try:
            manifest = self._describing.describe(address)
            if manifest is None:
                return f"{address} is not a container anything here can describe"
            self._cataloguing.record(dataset_id, address, manifest)
        except Exception as failed:
            return f"what is inside {address} was not recorded: {failed}"
        return None


__all__ = ["ENDINGS", "Session"]
