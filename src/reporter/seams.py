"""The four outward seams, named for what this reporter does through them.

A seam is a Protocol here and an adapter under `reporter.adapters`, so
which engine publishes, which store keeps the data, and how the keeper is
reached are choices a deployment makes at its entrypoint. That is the
arrangement `apps/conductor` and `apps/thinker` both use, and the reason
is the same one three times over.

None of the Protocols carries a Port suffix. Everything in this module is
a seam, so saying so distinguishes nothing, and `apps/keeper` forbids the
suffix for that reason.

## Named for the need, not for what answers it

`Reporting` and `Filing` both reach the keeper today, and one adapter
implements both. They are two Protocols anyway, because they are two
capabilities: one records what an engine did to a step's run, the other
records where the data that run produced is being kept. The keeper
serving both is a fact about the deployment rather than about what this
reporter needs, and a single Protocol carrying both verbs would hand
every caller a verb it must never call.

A name that says what is on the other side goes stale the moment
something else answers. A name that says what the caller needs cannot,
because the caller is what it describes.

## The absence of a capability is how the dataset leg switches off

A deployment with no store has no `Filing` and no `Locating`, and
`Session` reads the two absences as "this reporter does not do that".
It used to read a configuration table instead, and ask it again at each
of the three places the answer mattered. There is nothing left to
disagree with itself: a session that cannot file was not given the
capability.

## What can go wrong, in three kinds and no status codes

An adapter raises `UnavailableError`, `RefusedError` or `DisagreedError`, and nothing
else. Those are the only three distinctions anything above needs:

    UnavailableError  no answer came, and asking again may get one
    RefusedError      the answer was no, and waiting will not change it
    DisagreedError    the record says the run is not where this expects

They replaced two exceptions that each carried an HTTP status. Every
caller then had to interpret one: `Session` asked whether a status was
worth retrying, and `Relay` caught two transport-specific classes by
name to decide the same thing. Both were reading the wire's vocabulary
to recover a distinction the adapter already knew and had thrown away.
Mapping a status onto one of these three is the adapter's work, and
doing it there is what leaves one place where that mapping is written.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime
    from uuid import UUID

    from reporter.intents import RegisterDataset, ReportStepRun


Delivery = tuple[str, "Mapping[str, Any]"]
"""One thing that arrived, as whatever delivered it named it.

A name and a payload this package does not open until something
engine-shaped does. A published document is one thing that fits and not
the only one, which is why neither word here says document.
"""

Delivering = "Iterator[Delivery]"
"""Where deliveries come from, until they run out or somebody stops them.

An alias rather than a Protocol, deliberately. The capability is exactly
what `Iterator` already describes, and declaring a second protocol with
one `__iter__` on it would be inventing a name for something the standard
library has. What the alias buys is the name: a source is `Delivering`
wherever one is passed, so the seam is findable even though the type
behind it is borrowed.

It is also the one seam nothing here calls. A subscription is pulled from
and an engine in the same process pushes into `Relay.submit` instead, so
there is no verb the two shapes share to put on a Protocol.
"""


class UnavailableError(Exception):
    """Nothing answered, and asking again may get an answer.

    A socket that did not connect, a request that timed out, a service
    saying it is too busy or briefly broken. The delivery is not finished
    with, and `Relay` is what asks again.

    An adapter that lets its own transport's exception escape instead of
    raising this has made a failure nothing above recognises. The worker
    then dies on a class it does not catch, and a reporter whose worker
    has died looks exactly like a beamline that is not running.
    """


class RefusedError(Exception):
    """The answer was no, and waiting will not change it.

    A step the keeper does not hold, a body it will not accept, a
    credential it does not honour. The delivery is finished with and
    becomes `Held`, because somebody has to look at it and nothing
    automatic will fix it.
    """


class DisagreedError(Exception):
    """The record says the run is not where this report assumes it is.

    Kept apart from `RefusedError` because the two want opposite handling and
    one of them is ordinary. A redelivery of a report the record already
    holds arrives here, and so does a report for a run that went
    somewhere else entirely. Nothing on this side can tell those apart,
    which is why the outcome is named `Unchanged` for its effect.

    `detail` is what the far side said, and it is a field rather than
    just the message because it is copied onto that outcome. What makes
    a harmless replay distinguishable from a reporter talking about the
    wrong step is whatever names the state actually held, so an adapter
    puts that here and keeps its own routing out of it.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True)
class Location:
    """Where one body of data is, and when whatever wrote it finished.

    `occurred_at` is `None` when the store holds no ending for the run,
    and that is worth reading as a signal rather than as a missing field.
    A store that has the node but not its ending is a store this reporter
    got to first, which in one process means it subscribed before the
    writer rather than after it. The keeper then stamps the moment it was
    told, so nothing is lost but the record is less true than it could be.
    """

    path: str
    occurred_at: datetime | None


@runtime_checkable
class Reporting(Protocol):
    """Recording what an engine did to the run one step opened."""

    def record(self, intent: ReportStepRun) -> None:
        """Say what happened, or raise one of the three.

        `DisagreedError` is the one worth naming here, because it is the only
        seam that raises it: a report is about a run's progress through
        states, so it is the only thing this reporter sends that the
        record can already be past.
        """
        ...


@runtime_checkable
class Filing(Protocol):
    """Recording where the data a run produced is being kept."""

    def record(self, intent: RegisterDataset) -> UUID:
        """File one address, and return the id of the record it made.

        Filing the same address twice must return the first record's id
        rather than making a second one. A reporter that is restarted
        re-sends whatever was in flight, and a store address is the one
        thing both attempts agree on, so the far side is where that
        agreement has to be turned into one record.

        Nothing here carries the scheme the address belongs to. That is a
        fact about the store a deployment keeps its data in, so whatever
        implements this was told it when it was built.
        """
        ...


@runtime_checkable
class Locating(Protocol):
    """Asking where a run's output ended up."""

    def locate(self, run_reference: str) -> Location | None:
        """The data that run produced, or `None` if there is none.

        `None` is an answer rather than a failure: a run the store does
        not hold is a run that wrote nothing there, which is ordinary at
        a beamline where not every scan keeps its readings.

        `run_reference` is the engine's own id for the run, because a
        store watching an engine files under the engine's names.
        """
        ...


__all__ = [
    "Delivering",
    "Delivery",
    "DisagreedError",
    "Filing",
    "Locating",
    "Location",
    "RefusedError",
    "Reporting",
    "UnavailableError",
]
