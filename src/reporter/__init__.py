"""Turns one engine's document stream into AROC's run commands.

A client of AROC, not a part of it. The direction Execution commits to is
reported: an engine runs a routine and something tells AROC afterwards. So
the dependency arrow points into AROC, and a thing that calls an HTTP API
needs a URL and a token rather than a port declared for it. Nothing in
`apps/api` imports this package and nothing here imports `aroc`.

Two halves that do not import each other. `Translator` turns one engine's
documents into the intents in `intents`, and `Session` acts on an intent
against AROC and says what came of it. Only the first half knows which
engine this is, which is what a second engine having no documents in it
taught us, and `documents_into` in `wire` is the one place they are
joined. `Relay` puts a queue and a thread in front of both, so an engine
handing a document over waits on nothing, and `sources` is where documents
come from: a live engine publishing over 0MQ, or a capture on disk.

What is still missing is durability. Nothing remembers how far it has
read, and nothing it is subscribed to remembers either, so a document
published while this is down is a document lost. See the README.
"""

from reporter.client import (
    ArocClient,
    HttpClient,
    RequestRefusedError,
    Response,
    idempotency_key_for,
)
from reporter.config import ConfigError, ReporterConfig, from_mapping, load
from reporter.intents import Ignored, Intent, ReportRun, Transition, Unmappable, Verb
from reporter.outcomes import Held, Moved, Outcome, Recorded, Skipped, Unchanged
from reporter.relay import Handle, Relay
from reporter.session import Session, is_worth_retrying
from reporter.sources import DecodeError, Delivery, from_capture, from_subscription
from reporter.translate import Translator, engine_instant
from reporter.wire import documents_into

__all__ = [
    "ArocClient",
    "ConfigError",
    "DecodeError",
    "Delivery",
    "Handle",
    "Held",
    "HttpClient",
    "Ignored",
    "Intent",
    "Moved",
    "Outcome",
    "Recorded",
    "Relay",
    "ReportRun",
    "ReporterConfig",
    "RequestRefusedError",
    "Response",
    "Session",
    "Skipped",
    "Transition",
    "Translator",
    "Unchanged",
    "Unmappable",
    "Verb",
    "documents_into",
    "engine_instant",
    "from_capture",
    "from_mapping",
    "from_subscription",
    "idempotency_key_for",
    "is_worth_retrying",
    "load",
]
