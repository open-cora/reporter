"""The five outward seams, named for what this reporter does through them.

A seam is a Protocol here and an adapter under `reporter.adapters`, so
which engine publishes, which store keeps the data, and how the keeper is
reached are choices a deployment makes at its entrypoint. That is the
arrangement `apps/conductor` and `apps/thinker` both use, and the reason
is the same one three times over.

Five seams and four Protocols, because `Delivering` is an alias rather
than a Protocol for the reason given where it is defined.

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

`Describing` is absent on its own terms rather than with those two. A
deployment can know where data landed and still have nothing able to
read the format it landed in, which is the ordinary case at a beamline
whose files are a kind nothing here has an adapter for yet.

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


MANIFEST_MAX_ENTRIES = 64
"""How many entries one manifest may carry.

Derived from a real file rather than chosen. The 12 GB DXchange file at
19-BM holds 140 nodes, 109 of them datasets, and the useful description
of it is five entries: three arrays and two regions named and counted.
The bound has to leave a real container comfortable and make dumping a
tree impossible, and 64 sits inside that gap.

It is a contract and not a truncation point. An adapter that meets a
container with more than this summarizes before it builds a manifest,
because silently keeping the first sixty-four would hand a reader
something that looks complete and is not.
"""

ENTRY_PATH_MAX_LENGTH = 512
"""Long enough for a deep tree, short enough to not be a payload."""

LABEL_MAX_LENGTH = 64
"""The bound on a convention, a role and a dtype.

One constant for three fields because they are one kind of thing: a
short word from a vocabulary nobody here owns.
"""


class InvalidManifestError(ValueError):
    """A manifest, entry or extent was built outside what it may hold.

    Raised at construction rather than checked by a caller, so an
    adapter author meets it while writing the adapter. It is not one of
    the three seam errors on purpose: those say what happened on the
    other side of a seam, and this says the thing being handed back is
    not a manifest.
    """


@dataclass(frozen=True)
class Extent:
    """How much of something there is, and of what.

    `shape` carries one of two things and `dtype` says which. With a
    dtype this describes an array and the shape is its dimensions.
    Without one it describes a container and the shape is a single
    number: how many files a set holds, how many children a region has.
    That is checked below rather than left as a reading convention,
    because a container counted by two numbers is nobody's intent.

    One field rather than two because a set of files and a region of a
    tree are the same case, a thing and how many are in it, so a second
    field would sit empty on every array and this one would sit empty
    on every container. The real file that settled this holds three
    arrays and five regions, so both halves are ordinary.

    `capacity` is what the container reserved, when the container says.
    It is the difference between a scan that collected one flat field
    and a scan that meant to collect a hundred, which is a question
    worth asking and is invisible from `shape` alone. `None` where a
    format has no such notion, which is most of them.

    `dtype` is the element type as the format spells it, carried rather
    than interpreted, for the same reason the thinker carries the
    keeper's words for how a step ended.
    """

    shape: tuple[int, ...]
    capacity: tuple[int, ...] | None
    dtype: str | None

    def __post_init__(self) -> None:
        if any(dimension < 0 for dimension in self.shape):
            raise InvalidManifestError(
                f"a shape counts things, so {self.shape} cannot hold a negative"
            )
        if self.dtype is None and len(self.shape) != 1:
            raise InvalidManifestError(
                f"without a dtype this describes a container, and a container is counted "
                f"by one number rather than by {self.shape}"
            )
        if self.capacity is not None and len(self.capacity) != len(self.shape):
            raise InvalidManifestError(
                f"capacity {self.capacity} and shape {self.shape} describe the same thing "
                "and must have the same number of dimensions"
            )
        _refuse_empty(self.dtype, "dtype")


@dataclass(frozen=True)
class Entry:
    """One thing inside a container, and what a convention calls it.

    Three fields, and the absences are the design. What is deliberately
    unreachable here is any number computed from the data: there is
    nowhere to put a mean, a sigma or a signal-to-noise ratio, and that
    is the point rather than an oversight. A description exists to say
    whether a thing is worth opening and must never become a way to
    answer without opening it, which is the difference between an index
    and a cache. A rule saying so could be read and ignored; a closed
    shape cannot.

    `role` is what a convention calls this entry, and it is `None`
    whenever no convention names it. Absence means nobody knows, never
    that there is nothing, and the two are different answers. The same
    refusal governs a device with no group: inventing one would
    manufacture a fact.

    Nothing here owns the vocabulary roles are drawn from. `group` in
    the device register is free-form for the same reason and has been
    converging without help: four beamlines independently say
    `sample-stack`. A word three adapters reach for has earned agreement,
    and a word one adapter reaches for costs nothing.
    """

    path: str
    extent: Extent | None
    role: str | None

    def __post_init__(self) -> None:
        if not self.path.strip():
            raise InvalidManifestError("an entry's path names where it is, so it cannot be blank")
        if len(self.path) > ENTRY_PATH_MAX_LENGTH:
            raise InvalidManifestError(
                f"a path of {len(self.path)} is past {ENTRY_PATH_MAX_LENGTH} "
                "and is becoming a payload"
            )
        _refuse_empty(self.role, "role")


@dataclass(frozen=True)
class Manifest:
    """What is in one body of data, as whatever can read it reports.

    Not the data, and not its metadata either. A manifest lists a
    shipment and is never the shipment, which is the whole of what this
    is for: a reader deciding whether to open twelve gigabytes should be
    able to decide from this, and should get nothing from it that would
    let it skip opening.

    `convention` names the vocabulary the entries are drawn from, not
    the way they are addressed. It is deliberately not called a scheme:
    the scheme an address carries says how to reach a thing, and this
    says how to read it, which are different enough to deserve
    different words. `unknown` is an honest value, and an adapter that
    reports it reports entries with no roles.
    """

    convention: str
    entries: tuple[Entry, ...]

    def __post_init__(self) -> None:
        if not self.convention.strip():
            raise InvalidManifestError(
                "a convention names the vocabulary these entries use, and 'unknown' says "
                "there is none. A blank one says nothing at all."
            )
        if len(self.convention) > LABEL_MAX_LENGTH:
            raise InvalidManifestError(f"a convention is a short word, not {len(self.convention)}")
        if len(self.entries) > MANIFEST_MAX_ENTRIES:
            raise InvalidManifestError(
                f"{len(self.entries)} entries is past {MANIFEST_MAX_ENTRIES}. A container with "
                "that much in it is summarized before it is described, because a manifest "
                "holding the first few looks complete and is not."
            )


def _refuse_empty(label: str | None, field: str) -> None:
    """Absence is `None`, never a blank string.

    Two spellings of "nobody knows" would make the vocabulary above
    impossible to count: one adapter reporting `None` and another
    reporting `""` would read as two different answers.
    """
    if label is not None and not label.strip():
        raise InvalidManifestError(f"{field} is absent as None, not as an empty string")
    if label is not None and len(label) > LABEL_MAX_LENGTH:
        raise InvalidManifestError(f"{field} is a short word from a vocabulary, not {len(label)}")


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


@runtime_checkable
class Describing(Protocol):
    """Asking what is inside one body of data, without reading it."""

    def describe(self, address: str) -> Manifest | None:
        """What is in there, or `None` if there is nothing to describe.

        `None` is an answer rather than a failure, the way `Locating`'s
        is: a container this reader does not understand is not a broken
        request, and reporting no manifest says more honestly than an
        empty one that nothing was learned. Unreadable is different and
        raises `UnavailableError`, because asking again may work.

        The address is the one already filed, so whatever implements
        this was told at build time how to open what that names, the
        same way the scheme is a build-time fact for `Filing`.

        What this must not do is open the data. Reading a frame to
        report its mean would make a reader able to skip reading, which
        is the one thing a description is not for, and `Entry` is shaped
        so that there is nowhere to put the answer.
        """
        ...


__all__ = [
    "ENTRY_PATH_MAX_LENGTH",
    "LABEL_MAX_LENGTH",
    "MANIFEST_MAX_ENTRIES",
    "Delivering",
    "Delivery",
    "Describing",
    "DisagreedError",
    "Entry",
    "Extent",
    "Filing",
    "InvalidManifestError",
    "Locating",
    "Location",
    "Manifest",
    "RefusedError",
    "Reporting",
    "UnavailableError",
]
