"""What translating one delivery produces, before anything is sent.

Four outcomes, in two groups. `ReportStepRun` and `RegisterDataset` each
name a command the keeper publishes and carry everything that command needs.
`Ignored` and `Unmappable` both mean nothing will be sent, and they are
separate because the reasons are opposite: one is the design working and
the other is the design out of date.

The first two cover two bounded contexts, and that is deliberate. This
file is the description of everything the reporter can ask the keeper for, so a
command missing from it is a command nobody reading this knows about.

## Every intent carries the keeper's own ids, and none carries a name

This used to be the other way round. A `ReportRun` carried a plan NAME
and whatever sent it had to turn that into a keeper plan id from a
configured map, because a run was a record this reporter brought into
existence and the keeper had never heard of the work before the report arrived.

The keeper now composes the work itself. It writes a Procedure, dispatches an
Execution, and whatever drives that execution carries the execution and
step ids into the engine's own metadata. So the reference is on the
delivery, this reporter creates nothing, and the plan map is gone along
with every refusal that depended on it.

That is a smaller job and a stricter one. A document carrying no keeper
reference describes work this system never asked for, and there is
nothing to record it against: see `translate` for why that is `Ignored`
rather than an alert.

Nothing here carries parameters either, and the omission is the same
fact. A `ReportRun` had to carry what the engine was called with, because
the keeper's record of the run was being made from it, and the reporter had to
drop every argument that was a device repr rather than a value. The keeper now
holds those values on the procedure it composed, so what the engine says
it was called with is at best a second copy and at worst a disagreement
this system cannot adjudicate.

Each intent that can produce an alert carries an `origin`: a short label
naming whatever in the engine's stream this came from. It is there so a
`Held` can say what to go and look at, and it is a plain string rather
than anything document-shaped because a second engine's stream is not
made of documents. For this translator it is a document name.

Keeping these as values rather than calls is what makes the translation
testable against a captured file. Every finding the spike printed is a
statement about which of these four a delivery produces, and a value can
be asserted where a POST cannot.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

Report = Literal["Started", "Paused", "Resumed", "Completed", "Aborted", "Failed"]
"""The six things an engine can be reported to have done to one run.

Spelled exactly as the keeper's `EngineReport` spells them, because these go
into a request body as they are. A `Literal` rather than an enum because
they are wire strings and the only thing worth checking is that a typo
cannot reach a request.

Six where the run transitions were five, and the extra one is `Started`.
A run had to be created before it could move, so starting was a different
command with a different shape; a step already exists, so opening its run
is the first of six reports about it and carries no more than the others.
"""


@dataclass(frozen=True)
class ReportStepRun:
    """An engine did something to the run one acquisition step opened.

    One intent for all six reports, because the keeper takes them on one
    endpoint with the verb in the body. That is itself a decision made
    for this caller: a reporter turns each document into whichever of six
    it is, so a path per verb would make it build a URL by lookup.

    `execution_id` and `step_id` come from the engine's own metadata,
    where whatever dispatched the work put them. They are not resolved,
    guessed or looked up, which is the whole difference from the run
    reference this replaced.

    `engine_reference` is the engine's own id for the run. The keeper records
    it on a start and ignores it on the others, and this carries it every
    time because the store leg below asks a store about it by that name.
    """

    execution_id: UUID
    step_id: UUID
    reported: Report
    engine_reference: str
    occurred_at: datetime | None
    origin: str


@dataclass(frozen=True)
class RegisterDataset:
    """An acquisition produced data, and a store is keeping it at this address.

    The Custody half of the vocabulary, and the reason this file describes
    the whole job rather than most of it.

    It names the same step the report above does, because data belongs to
    one acquisition rather than to a whole traversal. An execution may
    acquire several times and each acquisition writes its own data, which
    at a tomography beamline is the sample position.

    `external_ref_value` is the store's address for the data and nothing
    else: not a file path, because a run's readings are often rows in a
    table with no file to point at, and not a copy of what the store knows
    about the data. The scheme it belongs to is configuration, so it is
    not on the intent.

    `occurred_at` is when whatever wrote the data finished, as the store
    reports it. `None` when the store holds no ending yet, and the keeper then
    stamps the moment it was told, which is honest and less precise.
    """

    execution_id: UUID
    step_id: UUID
    external_ref_value: str
    occurred_at: datetime | None
    origin: str


@dataclass(frozen=True)
class Ignored:
    """A delivery with nothing in it for the keeper, which is expected.

    Most of a stream is this: the parts that describe what is about to be
    read, or carry the readings themselves, rather than saying anything
    about a run's life. A document from work the keeper never dispatched is
    this too. `reason` is filled in so a caller can count what it is
    skipping without the skip being an event.
    """

    reason: str


@dataclass(frozen=True)
class Unmappable:
    """A delivery this translator handles, carrying something it cannot map.

    Distinct from `Ignored`, and the distinction is the point. An
    unrecognised `exit_status` is either a bug here or an engine that has
    grown a fourth ending, and both are worth somebody's attention. A
    descriptor producing nothing is neither. The spike put both in one
    list, so the second kind was invisible among the first.
    """

    reason: str
    origin: str


Intent = ReportStepRun | RegisterDataset | Ignored | Unmappable

__all__ = [
    "Ignored",
    "Intent",
    "RegisterDataset",
    "Report",
    "ReportStepRun",
    "Unmappable",
]
