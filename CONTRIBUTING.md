# Contributing

The reporter is a personal research repository: it relays one
acquisition engine's document stream to the keeper. It is public so the work can be read, cited, and learned from, not
because it is soliciting contributions.

## Where the code is developed

This repository is a published mirror. The work happens in
[open-cora/cora](https://github.com/open-cora/cora), a development tree holding
this project, the keeper it talks to and its sibling clients side by side,
and this repository is extracted from `apps/reporter` with `git subtree`, so the
history here is the real history rather than a squashed import.

That matters for one practical reason: a change merged here would be
overwritten by the next publish. Open an issue, or fork, and say which of the
two trees you read. Everything below applies to a change made in either place.

## What is welcome

- **Questions and corrections.** If a document states something false, a
  convention contradicts the code, or a guarantee is claimed that nothing
  provides, please open an issue. That class of defect is the one this
  project most wants reported.
- **A second engine.** `translate` and `sources` read one engine and nothing
  else does, so a second engine should be a translator rather than a
  rewrite. If you try one and it does not fit, the split is wrong and that is
  worth an issue.

## What is unlikely to be merged

- **Drive-by code pull requests.** The architecture is deliberate and most of
  it is documented in [docs/](docs/index.md). A change that reads as an
  improvement in isolation often violates a rule written down somewhere else,
  and reviewing that costs more than the change saves.
- **Dependency bumps and formatting changes.** These are handled in bulk.
- **Anything that crosses the split.** One half reads an engine and one half talks to the
  keeper. A helper filed on the wrong side broke that once already, worked
  perfectly, and was caught by nobody.

If you want to build on this, fork it. That is the intended use.

## If you do send a change

Read [docs/conventions.md](docs/conventions.md) first. In short:

```bash
make install      # uv sync
make precommit    # install the hooks, including the pre-push pass
make lint typecheck
make test
```

Three things that are easy to get wrong here:

1. **Stage your files before trusting a green run.** Every structural and
   prose rule enumerates through `git ls-files`, so a file git has never seen
   is invisible to all of them. A green run on unstaged work means nothing.
2. **A new test must be able to fail.** Break the thing it names and watch it
   go red before you trust it. Several checks in this project's sibling trees
   were found to be testing nothing exactly this way.
3. **The captures are evidence, not fixtures to keep green. A red test
   after `make refresh-captures` names a finding that moved; the diff is
   mostly ids and timestamps. Commit a new capture only as part of reacting
   to a red test.**

Commits follow Conventional Commits with a scope; the subject says what and
the body says why.

## Relationship to the keeper

This is a client of [the keeper](https://github.com/open-cora/keeper) and not
a part of it. The dependency arrow points one way: a reporter dials the keeper and
the keeper never dials back, and a document published while the reporter is
down is a document lost. The README says so.

There is no shared package. What binds the two is prose, in
[docs/client-contract.md](docs/client-contract.md), plus two metadata keys
that each side pins to literals in a test of its own. That is the whole
contract, and it is written down in both repositories on purpose: a copy that
drifts is caught by the pins rather than by a reader.

A patch here does not reach the keeper, and vice versa.

## License

Contributions are accepted under the [Apache-2.0](LICENSE) license of the
project.
