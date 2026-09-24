"""What handling one delivery came to, for whoever is driving.

The mirror of `intents`. An intent is what a delivery meant before
anything was sent; an outcome is what happened when it was. Five of them,
and the split is by what the caller should do rather than by what
occurred, because a subscription loop has exactly two decisions to make:
whether to advance its checkpoint, and whether to wake somebody.

    Relayed      AROC now holds what the engine said about a step
    Kept         a step's run ended, and what it produced is recorded too
    Unchanged    AROC declined, because the step is not where the
                 delivery expects it to be
    Skipped      the delivery said nothing this system asked for
    Held         it said something and could not be acted on

Advance the checkpoint on all five. Every one of them is settled: sending
the same delivery again produces the same outcome, so there is nothing to
come back for. Only `Held` is worth waking somebody, and only some of them
urgently.

`Recorded` used to be here, for a start that became a run AROC did not
previously hold. It is gone because this reporter no longer brings
anything into existence: every record it touches was created by AROC
before the engine was asked to do anything.

What is NOT here is a retry. A request that never arrived, or one AROC
refused with a 429 or a 5xx, raises out of `Session.act` instead, so a
caller that swallows outcomes cannot swallow those too. The distinction is
the one that matters for a checkpoint: an outcome means "this delivery is
done with", and an exception means "ask me again".
"""

from dataclasses import dataclass
from uuid import UUID

from reporter.intents import Report


@dataclass(frozen=True)
class Relayed:
    """AROC accepted what the engine said about one step's run."""

    execution_id: UUID
    step_id: UUID
    reported: Report


@dataclass(frozen=True)
class Unchanged:
    """AROC declined the report, and its record is as it was.

    Named for the effect rather than the cause, because a 409 covers two
    situations this cannot tell apart on its own: the step's run is
    already past the state the delivery asks for, which is what a
    redelivery looks like, or the engine went somewhere else entirely and
    this is the wrong report for it. `detail` carries what AROC said,
    which names the state the run is actually in, and that is what
    separates a harmless replay from a reporter talking about the wrong
    step.

    Separate from `Held` because the first situation is the system
    working. One outcome covering both would teach whoever reads the
    alerts to ignore the one that matters.

    Separate from `Skipped` too, and the difference is worth holding on
    to: `Skipped` means nothing was sent, this means something was sent
    and declined.
    """

    execution_id: UUID
    step_id: UUID
    reported: Report
    detail: str


@dataclass(frozen=True)
class Kept:
    """A step's run ended, and the data it produced is recorded as well.

    Replaces `Relayed` for an ending, rather than arriving beside it, and
    the reason is that one intent gets one outcome. A stop means two
    things now, the run finishing and its data existing, so the outcome
    for it names both.

    The cost is in the other direction and is worth knowing before
    reading a tally: when the report lands and the dataset cannot be
    registered, the one outcome has to be `Held`, because somebody needs
    waking. So a session run against a store that is down reports no
    `Relayed` at all even though every report landed. The reports are in
    AROC either way and `Held` names the store as it happens; it is the
    summary that misleads, not the record.

    `reported` is `None` when no engine report arrived with the
    registration, which is what anything other than the ending delivery
    produces: a sweep of a store, a backfill, a repair by hand. The two
    cases are worth telling apart in a log, because one says a run just
    finished and the other says somebody found data for one that finished
    earlier.

    `external_ref_value` is the address the store gave, carried so a
    caller can print what it filed without asking AROC back.
    """

    execution_id: UUID
    step_id: UUID
    reported: Report | None
    dataset_id: UUID
    external_ref_value: str


@dataclass(frozen=True)
class Skipped:
    """The delivery carried nothing this system asked for.

    Most of a stream. The parts that describe what is about to be read, or
    carry the readings themselves, rather than saying anything happened,
    and everything belonging to work AROC never dispatched.
    """

    reason: str


@dataclass(frozen=True)
class Held:
    """Something this reporter should have acted on, and could not.

    The only outcome worth an alert, and the reasons differ in urgency:

        a delivery that cannot be       a bug here, or an engine that
        mapped                          grew an ending nobody knows
        a step AROC does not hold       the reference in the engine's
                                        metadata names nothing, which
                                        means whatever wrote it and AROC
                                        disagree
        the store holds nothing for     the data is late, or the writer
        a run that ended                is pointed somewhere else
        AROC refused, terminally        a grant is missing

    The first entry that used to be here, a plan name with no configured
    id, is gone with the plan map.

    Retrying produces this again, which is why it is an outcome and not
    an exception.

    `origin` names whatever in the engine's stream this came from, so an
    alert says where to look. It is carried through from the intent.
    """

    reason: str
    origin: str


Outcome = Relayed | Kept | Unchanged | Skipped | Held

__all__ = [
    "Held",
    "Kept",
    "Outcome",
    "Relayed",
    "Skipped",
    "Unchanged",
]
