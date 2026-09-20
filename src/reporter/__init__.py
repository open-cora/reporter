"""Turns one engine's document stream into AROC's run commands.

A client of AROC, not a part of it. The direction Execution commits to is
reported: an engine runs a routine and something tells AROC afterwards. So
the dependency arrow points into AROC, and a thing that calls an HTTP API
needs a URL and a token rather than a port declared for it. Nothing in
`apps/api` imports this package and nothing here imports `aroc`.

Half built. What exists is the core that turns documents into intents and
the client that sends them. What subscribes to an engine and what
remembers how far it has read are still to come, and they are one
decision rather than two; see the README for what it is waiting on.
"""

from reporter.client import ArocClient, HttpClient, RequestRefusedError, Response
from reporter.config import ConfigError, ReporterConfig, from_mapping, load
from reporter.intents import Ignored, Intent, ReportRun, Transition, Unmappable, Verb
from reporter.translate import Translator, engine_instant, idempotency_key_for

__all__ = [
    "ArocClient",
    "ConfigError",
    "HttpClient",
    "Ignored",
    "Intent",
    "ReportRun",
    "ReporterConfig",
    "RequestRefusedError",
    "Response",
    "Transition",
    "Translator",
    "Unmappable",
    "Verb",
    "engine_instant",
    "from_mapping",
    "idempotency_key_for",
    "load",
]
