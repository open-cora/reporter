---
template: home.html
---

# Reports what an acquisition engine did.

Relays one engine's document stream to the keeper as reports about the steps the
keeper dispatched, and says where the data those steps produced is being kept.

It runs where the engine is; the keeper runs where the database is. Everything it
files is something the record was told rather than something it checked, and
nothing here claims otherwise.

It creates nothing. The keeper composes the procedure, dispatches the execution and
holds the record, and a report naming no dispatched step is refused at the far end.

## What is here

The code, and the pages that outlive any one reading of it. The package's own
`README.md` is the design document: the split that makes a second engine a
translator rather than a rewrite, what each intent carries, and what this
deliberately will not promise.

| Page | Subject |
| --- | --- |
| [Client contract](client-contract.md) | The agreement with the keeper and with the conductor: two names for one acquisition, and the two metadata keys that join them |
| [Conventions](conventions.md) | How this project is written: naming, docstrings, comments, commits, test names |
| [Glossary](glossary.md) | The words shared with the keeper, and what each is pinned to |

What this package knows about a real engine and a real store is recorded rather
than assumed: two capture files, re-recordable with `make refresh-captures`, and
a suite whose assertions are written against the structural claims they hold.
