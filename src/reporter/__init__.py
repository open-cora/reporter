"""Relays one engine's document stream to AROC as step-run reports.

A client of AROC, not a part of it. The dependency arrow points into
AROC, and a thing that calls an HTTP API needs a URL and a token rather
than a port declared for it. Nothing in `apps/api` imports this package
and nothing here imports `aroc`.

**This reporter creates nothing.** AROC composes a procedure, dispatches
an execution, and whatever drives that execution carries the step's AROC
ids into the engine's own metadata. What arrives here is an engine
talking about work this system already wrote down, so every intent names
a record that exists and none of them brings one into being. That is the
whole of what changed when Execution stopped recording runs, and it is
why there is no plan map, no external-reference lookup, and no command
here that can be refused for naming something AROC has never heard of.

A document with no AROC reference is a scan somebody ran by hand. It is
skipped, and `translate` says why that is quiet rather than loud.

Two halves that do not import each other. `Translator` turns one engine's
documents into the intents in `intents`, and `Session` acts on an intent
against AROC and says what came of it. Only the first half knows which
engine this is, which is what a second engine having no documents in it
taught us, and `documents_into` in `wire` is the one place they are
joined. `Relay` puts a queue and a thread in front of both, so an engine
handing a document over waits on nothing, and `sources` is where documents
come from: a live engine publishing over 0MQ, or a capture on disk.

`stores` is the second thing this reads and the reason it reports into two
bounded contexts rather than one. An engine says what it did to one
step's run; a store says where the data that step produced is being kept.
A deployment with no store configured leaves the whole of that leg
switched off.

What is still missing is durability. Nothing remembers how far it has
read, and nothing it is subscribed to remembers either, so a document
published while this is down is a document lost. See the README.
"""

from reporter.client import (
    HttpClient,
    KeeperClient,
    RequestRefusedError,
    Response,
    dataset_key_for,
)
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
from reporter.session import Session, is_worth_retrying
from reporter.sources import DecodeError, Delivery, from_capture, from_subscription
from reporter.stores import (
    HttpStoreLookup,
    Location,
    StoreLookup,
    StoreRefusedError,
    node_path,
)
from reporter.translate import KEEPER_METADATA_KEYS, Translator, engine_instant, keeper_reference
from reporter.wire import documents_into

__all__ = [
    "KEEPER_METADATA_KEYS",
    "ConfigError",
    "DecodeError",
    "Delivery",
    "Handle",
    "Held",
    "HttpClient",
    "HttpStoreLookup",
    "Ignored",
    "Intent",
    "KeeperClient",
    "Kept",
    "Location",
    "Outcome",
    "RegisterDataset",
    "Relay",
    "Relayed",
    "Report",
    "ReportStepRun",
    "ReporterConfig",
    "RequestRefusedError",
    "Response",
    "Session",
    "Skipped",
    "StoreConfig",
    "StoreLookup",
    "StoreRefusedError",
    "Translator",
    "Unchanged",
    "Unmappable",
    "dataset_key_for",
    "documents_into",
    "engine_instant",
    "from_capture",
    "from_mapping",
    "from_subscription",
    "is_worth_retrying",
    "keeper_reference",
    "load",
    "node_path",
]
