# Reporter

Relays what one acquisition engine did to the keeper, and says where the data
it produced ended up.

A client of the keeper, not a part of it. It watches an engine's document
stream, turns each document into an intent, and sends the ones that matter.
Nothing here imports the keeper and nothing in the keeper imports this.

The package's own `README.md` is the design document: which documents become
which intents, why a run with no keeper reference is ignored rather than
flagged, what the relay guarantees on shutdown, and what is lost when the
process dies. These pages are the parts that outlive any one reading of the
code.

| Page | Subject |
| --- | --- |
| [Client contract](client-contract.md) | The agreement with the keeper and with the conductor: two names for one acquisition, and the two metadata keys that join them |
| [Conventions](conventions.md) | How this project is written: naming, docstrings, comments, commits, test names |
| [Glossary](glossary.md) | The words shared with the keeper, and what each is pinned to |

The test fixtures under `tests/` were recorded by driving a real engine and a
real store, by the two collectors in `scripts/`. Nothing in them was written by
hand, which is what makes them worth asserting against.
