"""Relays one engine's document stream to the keeper as step-run reports.

A client of the keeper, not a part of it. The dependency arrow points
into the keeper, and a thing that calls an HTTP API needs a URL and a
token rather than a port declared for it. Nothing in `apps/keeper`
imports this package and nothing here imports `keeper`.

**This reporter creates nothing.** The keeper composes a procedure,
dispatches an execution, and whatever drives that execution carries the
step's keeper ids into the engine's own metadata. What arrives here is
an engine talking about work this system already wrote down, so every
intent names a record that exists and none of them brings one into
being.

A delivery with no keeper reference is work somebody ran by hand. It is
skipped, and the translator says why that is quiet rather than loud.

## Six capabilities, and nothing here names what provides them

`seams` holds them. `Reporting` records what an engine did to one step's
run, `Filing` records where the data that run produced is being kept,
and `Cataloguing` records what is inside it. Those are two bounded
contexts and therefore separate Protocols even though one service
answers all three today. `Locating` asks a store where a run's output
went, `Describing` asks a container what it holds, and `Delivering` is
where deliveries come from.

Under `reporter.adapters` is what satisfies them, one module per outside
system, and nothing above that directory imports any of it. That is why
this module re-exports none of them: `import reporter` must not require
a socket library, an HTTP library or an engine.

`Session` acts on one intent against whatever it was given, `Relay` puts
a queue and a thread in front of it so an engine handing a delivery over
waits on nothing, and `intents` is the vocabulary between the two halves.

A deployment with no store gets no `Filing` and no `Locating`, which
switches the dataset leg off. The absence is the switch: nothing
consults a setting to find out.

What is still missing is durability. Nothing remembers how far it has
read, and nothing it is subscribed to remembers either, so a delivery
published while this is down is a delivery lost. See the README.
"""

from reporter.config import ConfigError, ReporterConfig, StoreConfig, from_mapping, load
from reporter.intents import (
    Ignored,
    Intent,
    RegisterDataset,
    Report,
    ReportStepRun,
    Unmappable,
)
from reporter.outcomes import Held, Kept, Outcome, Relayed, Skipped, Unchanged
from reporter.relay import Handle, Relay
from reporter.seams import (
    Delivering,
    Delivery,
    DisagreedError,
    Filing,
    Locating,
    Location,
    RefusedError,
    Reporting,
    UnavailableError,
)
from reporter.session import ENDINGS, Session

__all__ = [
    "ENDINGS",
    "ConfigError",
    "Delivering",
    "Delivery",
    "DisagreedError",
    "Filing",
    "Handle",
    "Held",
    "Ignored",
    "Intent",
    "Kept",
    "Locating",
    "Location",
    "Outcome",
    "RefusedError",
    "RegisterDataset",
    "Relay",
    "Relayed",
    "Report",
    "ReportStepRun",
    "ReporterConfig",
    "Reporting",
    "Session",
    "Skipped",
    "StoreConfig",
    "UnavailableError",
    "Unchanged",
    "Unmappable",
    "from_mapping",
    "load",
]
