# Repo guidance

This file is read by Claude Code (and other agents that respect `CLAUDE.md`).
Keep it as a pointer file, not a long doc; the real conventions live in
`docs/`.

## What this repo is

A reporter relays one acquisition engine's document stream to the keeper, as
reports about the steps the keeper dispatched, and says where the data those
steps produced is being kept.

It is a client of the keeper and not a part of it. The dependency arrow
points one way: a reporter dials the keeper and the keeper never dials back.
There is no shared package between them, and the wire contract is prose plus
two metadata keys pinned to literals on each side.

The chassis conventions came from the keeper's tree and are owned outright
from that point on. A fix here does not reach there.

## The split this package is built around

`translate` and `sources` read one engine and know nothing about the keeper.
`client`, `config`, `session` and `relay` talk to the keeper and know nothing
about any engine. `intents` is the vocabulary between them, and `wire` is the
one place they are joined.

That split is what makes a second engine a translator rather than a rewrite,
and nothing about it is visible in a diff. It was broken once already, by a
helper filed on the wrong side, and no test failed because there was no test.
`tests/test_the_halves_stay_apart.py` is that test.

## Conventions

- **Naming, documentation, commits, branch flow, test names**: [docs/conventions.md](docs/conventions.md)
- **Docstring + comment + test-doc style specifically**: [docs/conventions.md#documentation](docs/conventions.md#documentation)
- **What the keeper promises a client, and what it does not**: [docs/client-contract.md](docs/client-contract.md)
- **Glossary**: [docs/glossary.md](docs/glossary.md)

## Hard rules carried into every change

- No phase, iteration or audit tags in source: a plan coordinate, an
  iteration label, a dated audit tag, a numbered review finding. Git log is
  the right home, and `tests/test_no_phase_markers.py` spells every shape it
  refuses.
- No emoji anywhere in source: comments, docstrings, log strings, error messages.
- No em dashes in user-facing prose; use commas, colons, or rephrase.
- Default to no `#` comments. Add one only when the WHY is non-obvious.
- Test names carry scenarios (`test_<subject>_<scenario>_<expectation>`); per-test docstrings stay rare.
- A docstring may not name a symbol or a file that does not exist. Backticks mean "this is a symbol"; use a plain word when you mean a word.

## The rules that are actually enforced

Unusually for a package this size, every rule above except the comment
default is a test. They live beside the suite rather than in a tier of their
own, because there is one tier:

| File | Holds |
| --- | --- |
| `tests/test_no_em_dashes.py` | No em or en dash in source or prose |
| `tests/test_no_emoji.py` | No emoji in source or prose |
| `tests/test_no_phase_markers.py` | No plan coordinate or finding code |
| `tests/test_docstring_references_resolve.py` | Every backticked name and cited path resolves |
| `tests/test_test_names_carry_outcome.py` | A test name states a property |
| `tests/test_the_halves_stay_apart.py` | Neither half imports the other |

Each enumerates through `git ls-files`, so **a file git has never seen is
invisible to every one of them**. Stage new files before trusting a green
run.

## Two things that are easy to get wrong

**A new test must be able to fail.** Break the thing it names and watch it go
red before trusting it. Several checks in this project's sibling trees were
found to be testing nothing exactly this way.

**The captures are evidence, not fixtures to keep green.** `make
refresh-captures` re-records what a real engine and a real store do, and it
is deliberately unpinned. A red test after a refresh names the finding that
moved; the diff is mostly ids and timestamps. Commit a new capture only as
part of reacting to a red test, never on a whim.

## Memory hygiene

Auto-memory grows monotonically without a forcing function. These rules curb
drift between sessions. They apply to this repo's Claude auto-memory
directory: `~/.claude/projects/<repo-path-slug>/memory/`, where
`<repo-path-slug>` is the repository's absolute path with `/` replaced by `-`
(it differs per machine).

- A new memo's one-line pointer goes in `MEMORY.md` under the shelf that fits: a durable convention, principle, or pattern, a user fact, or feedback.
- Before creating a new memo, grep the index for the topic; prefer edit-in-place over a new file.
- Mutable status does not belong in index descriptions; the index carries the durable claim, the file carries the status.
- Any index description containing a count or a date older than 7 days requires a Read of the underlying file before quoting in chat.
- Memo files over ~300 lines: split into 2-3 sibling files linked from the first.

## Commits

One-line subject, body explains WHY. Recent commits set the tone; read
`git log --oneline -10`.
