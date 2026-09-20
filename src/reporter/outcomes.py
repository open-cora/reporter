"""What handling one document came to, for whoever is driving.

The mirror of `intents`. An intent is what a document meant before
anything was sent; an outcome is what happened when it was. Five of them,
and the split is by what the caller should do rather than by what
occurred, because a subscription loop has exactly two decisions to make:
whether to advance its checkpoint, and whether to wake somebody.

    Recorded     a run is now in AROC that was not
    Moved        a run changed state
    Unchanged    AROC declined, because the run is not where the
                 document expects it to be
    Skipped      the document said nothing about a run's life
    Held         it said something and could not be acted on

Advance the checkpoint on all five. Every one of them is settled: sending
the same document again produces the same outcome, so there is nothing to
come back for. Only `Held` is worth waking somebody, and only some of them
urgently.

What is NOT here is a retry. A request that never arrived, or one AROC
refused with a 429 or a 5xx, raises out of `Session.handle` instead, so a
caller that swallows outcomes cannot swallow those too. The distinction is
the one that matters for a checkpoint: an outcome means "this document is
done with", and an exception means "ask me again".
"""

from dataclasses import dataclass
from uuid import UUID

from reporter.intents import Verb


@dataclass(frozen=True)
class Recorded:
    """A start became a run AROC now holds."""

    run_id: UUID
    external_ref_value: str


@dataclass(frozen=True)
class Moved:
    """A run reached a new state, and AROC accepted it."""

    run_id: UUID
    verb: Verb


@dataclass(frozen=True)
class Unchanged:
    """AROC declined the transition, and its record is as it was.

    Named for the effect rather than the cause, because a 409 covers two
    situations this cannot tell apart on its own: the run is already past
    the state the document asks for, which is what a redelivery looks
    like, or the run went somewhere else entirely and this is the wrong
    verb for it. `detail` carries what AROC said, which names the state
    the run is actually in, and that is what separates a harmless replay
    from a reporter talking about the wrong run.

    Separate from `Held` because the first situation is the system
    working. One outcome covering both would teach whoever reads the
    alerts to ignore the one that matters.

    Separate from `Skipped` too, and the difference is worth holding on
    to: `Skipped` means nothing was sent, this means something was sent
    and declined.
    """

    run_id: UUID
    verb: Verb
    detail: str


@dataclass(frozen=True)
class Skipped:
    """The document carried nothing about a run's life.

    Most of a stream. Descriptors, readings, and the document types that
    exist to carry data rather than to say anything happened.
    """

    reason: str


@dataclass(frozen=True)
class Held:
    """Something this reporter should have acted on, and could not.

    The only outcome worth an alert, and the reasons differ in urgency:

        no plan configured for a name   an operator authored a plan and
                                        did not add it here. runs of it
                                        are being lost until they do.
        no run recorded for a uid       the start never arrived. usual
                                        when a reporter joins mid-run,
                                        and a real gap otherwise.
        a document that cannot be       a bug here, or an engine that
        mapped                          grew an ending nobody knows
        AROC refused, terminally        a grant is missing, or the plan
                                        map changed mid-run

    Retrying produces this again, which is why it is an outcome and not
    an exception.

    `origin` names whatever in the engine's stream this came from, so an
    alert says where to look. It is carried through from the intent.
    """

    reason: str
    origin: str


Outcome = Recorded | Moved | Unchanged | Skipped | Held

__all__ = [
    "Held",
    "Moved",
    "Outcome",
    "Recorded",
    "Skipped",
    "Unchanged",
]
