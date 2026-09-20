"""Turns one engine's document stream into AROC's run commands.

A client of AROC, not a part of it. The direction Execution commits to is
reported: an engine runs a routine and something tells AROC afterwards. So
the dependency arrow points into AROC, and a thing that calls an HTTP API
needs a URL and a token rather than a port declared for it. Nothing in
`apps/api` imports this package and nothing here imports `aroc`.

Hand a `Session` one document at a time and it does the rest: translate,
resolve, send, and report what came of it. What is still missing is only
the mouth of the pipe. Nothing here subscribes to an engine and nothing
remembers how far it has read, because those are one decision rather than
two and it is not made yet; see the README.
"""

from reporter.client import ArocClient, HttpClient, RequestRefusedError, Response
from reporter.config import ConfigError, ReporterConfig, from_mapping, load
from reporter.intents import Ignored, Intent, ReportRun, Transition, Unmappable, Verb
from reporter.outcomes import Held, Moved, Outcome, Recorded, Skipped, Unchanged
from reporter.session import Session, is_worth_retrying
from reporter.translate import Translator, engine_instant, idempotency_key_for

__all__ = [
    "ArocClient",
    "ConfigError",
    "Held",
    "HttpClient",
    "Ignored",
    "Intent",
    "Moved",
    "Outcome",
    "Recorded",
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
    "engine_instant",
    "from_mapping",
    "idempotency_key_for",
    "is_worth_retrying",
    "load",
]
