"""What translating one delivery produces, before anything is sent.

Five outcomes, in two groups. `ReportRun`, `Transition` and
`RegisterDataset` each name a command AROC publishes and carry everything
that command needs except the ids, which only something that can talk to
AROC can supply. `Ignored` and `Unmappable` both mean nothing will be
sent, and they are separate because the reasons are opposite: one is the
design working and the other is the design out of date.

The first three cover two bounded contexts, and that is deliberate. This
file is the description of everything the reporter can ask AROC for, so a
command missing from it is a command nobody reading this knows about.

Each of the three that can produce an alert carries an `origin`: a short
label naming whatever in the engine's stream this came from. It is there
so a `Held` can say what to go and look at, and it is a plain string
rather than anything document-shaped because a second engine's stream is
not made of documents. For this translator it is a document name.

Keeping these as values rather than calls is what makes the translation
testable against a captured file. Every finding the spike printed is a
statement about which of these five a delivery produces, and a value can
be asserted where a POST cannot.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

Verb = Literal["complete", "abort", "fail", "pause", "resume"]
"""The five run transitions, spelled as the path segment each one posts to.

A `Literal` rather than an enum because these are wire strings and the
only thing worth checking is that a typo cannot reach a URL. AROC's own
error classes are per-verb (naming rule R6), and the verb is on the
intent, so nothing here collapses a diagnostic.
"""


@dataclass(frozen=True)
class ReportRun:
    """A run happened, and AROC does not know about it yet.

    `plan_name` is the engine's handle rather than an AROC plan id, which
    is the whole of why the reporter needs a plan map: the id is not
    derivable from anything on the delivery, and two AROC plans may
    legitimately answer to one name.

    `dropped` names the `plan_args` keys that were left out. Every list
    the spike observed there held device reprs rather than device names,
    verbose and carrying configuration that changes between runs, and the
    clean names are on a different key. Dropping them is right and doing
    it silently is not, so the keys travel with the intent and whatever
    sends it can say what it left behind.
    """

    plan_name: str
    parameters: dict[str, Any]
    external_ref_value: str
    occurred_at: datetime | None
    origin: str
    dropped: tuple[str, ...] = ()


@dataclass(frozen=True)
class Transition:
    """A run this system already knows about moved.

    `run_uid` is the engine's id for the run, not AROC's. Resolving it is
    a lookup the sender does, from memory or from `GET /runs` after a
    restart.
    """

    run_uid: str
    verb: Verb
    occurred_at: datetime | None
    origin: str


@dataclass(frozen=True)
class Ignored:
    """A delivery with nothing in it for AROC, which is expected.

    Most of a stream is this: the parts that describe what is about to be
    read, or carry the readings themselves, rather than saying anything
    about a run's life. `reason` is filled in so a caller can count what
    it is skipping without the skip being an event.
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


@dataclass(frozen=True)
class RegisterDataset:
    """A run produced data, and a store is keeping it at this address.

    The Custody half of the vocabulary, and the reason this file describes
    the whole job rather than most of it.

    `run_uid` is the engine's id, not AROC's, exactly as on a `Transition`.
    Resolving it is the same lookup, which is what lets a dataset be
    reported by something that has never seen the run recorded.

    `external_ref_value` is the store's address for the data and nothing
    else: not a file path, because a run's readings are often rows in a
    table with no file to point at, and not a copy of what the store knows
    about the data. The scheme it belongs to is configuration, the way a
    run's is, so it is not on the intent.

    `occurred_at` is when whatever wrote the data finished, as the store
    reports it. `None` when the store holds no ending yet, and AROC then
    stamps the moment it was told, which is honest and less precise.
    """

    run_uid: str
    external_ref_value: str
    occurred_at: datetime | None
    origin: str


Intent = ReportRun | Transition | RegisterDataset | Ignored | Unmappable

__all__ = [
    "Ignored",
    "Intent",
    "RegisterDataset",
    "ReportRun",
    "Transition",
    "Unmappable",
    "Verb",
]
