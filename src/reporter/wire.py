"""How the two halves are joined, which is the only place they meet.

`translate` reads one engine's documents and knows nothing about AROC.
`session` acts against AROC and knows nothing about any engine. Neither
imports the other, and `intents` is the vocabulary between them.

Something has to put them together, and that something belongs above both
rather than inside either. This module is it, and it is deliberately the
smallest file in the package: a boundary is easiest to keep when crossing
it is one named function that a reader can find.

    sources ---> relay ---> documents_into ---> AROC
                              |
                              +-- translate.Translator   engine-shaped
                              +-- session.Session        AROC-shaped

A second engine writes its own translator, composes it here or beside
here, and reuses everything under `intents` unchanged. What that costs is
measured in a spike, against an engine whose
stream has no documents in it at all.
"""

from collections.abc import Mapping
from typing import Any

from reporter.outcomes import Outcome
from reporter.relay import Handle
from reporter.session import Session
from reporter.translate import Translator


def documents_into(session: Session) -> Handle:
    """One engine's documents, translated and then acted on.

    These two lines are the whole of what ties this reporter to a
    particular engine. Everything the returned function calls is either
    that engine's translator or a session that has never heard of it.

    The translator is created here rather than passed in because it holds
    one stream's state, so a caller with two streams wants two of these
    rather than one shared between them.
    """
    translator = Translator()

    def handle(name: str, document: Mapping[str, Any]) -> Outcome:
        return session.act(translator.feed(name, document))

    return handle


__all__ = ["documents_into"]
