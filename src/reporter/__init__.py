"""Turns one engine's document stream into AROC's run commands.

A client of AROC, not a part of it. The direction Execution commits to is
reported: an engine runs a routine and something tells AROC afterwards. So
the dependency arrow points into AROC, and a thing that calls an HTTP API
needs a URL and a token rather than a port declared for it. Nothing in
`apps/api` imports this package and nothing here imports `aroc`.

Half built. What exists is the functional core, the part that turns
documents into intents with no network in the way. What sends them, what
subscribes to an engine, and what remembers how far it has read are all
still to come; see the README for what each is waiting on.
"""

from reporter.intents import Ignored, Intent, ReportRun, Transition, Unmappable, Verb
from reporter.translate import Translator, engine_instant, idempotency_key_for

__all__ = [
    "Ignored",
    "Intent",
    "ReportRun",
    "Transition",
    "Translator",
    "Unmappable",
    "Verb",
    "engine_instant",
    "idempotency_key_for",
]
