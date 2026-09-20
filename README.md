# Reporter

Turns one engine's document stream into AROC's run commands.

**Half built.** What exists is the core that turns documents into intents,
and the client that sends them. What subscribes to an engine does not
exist yet. See [What is missing](#what-is-missing).

## What it is, and what it is not

A client of AROC, not a part of it. Execution's near-term direction is
*reported*: an engine runs a routine, and afterwards something tells AROC
that it did. That arrow points into AROC, so this is a thing that calls an
HTTP API rather than an adapter behind a port AROC declares.

Two consequences worth stating, because both look like accidents:

- **Nothing here imports `aroc`, and nothing in `apps/api` imports this.**
  Its own project and its own lockfile are what make that the
  interpreter's rule rather than a convention.
- **It runs where the engine is.** AROC runs where the database is. Two
  processes because two places.

It also has to name a particular engine on most of its pages, which
`apps/api` and `docs/` may not: which engine a deployment runs is a
deployment's fact, and a rule stated for one reads as a rule derived from
one. Being out here is how that stays true without an exception.

## The design in one picture

```
   engine documents            this package              AROC
   ----------------            ------------              ----
   start          ---->  ReportRun    ---------->  POST /runs
   event (pause)  ---->  Transition   ---------->  POST /runs/{id}/pause
   stop           ---->  Transition   ---------->  POST /runs/{id}/complete
   descriptor     ---->  Ignored               (nothing is sent)
   exit_status ?  ---->  Unmappable            (nothing is sent, loudly)

                         ^ translate.py        ^ client.py
                           pure, tested          every request asserted
                           against a real        through a recording
                           capture               transport
```

Nothing wires the left column to the right one yet. That is `session.py`,
and it waits on the subscription decision below.

`Ignored` and `Unmappable` are separate because the reasons are opposite.
A descriptor producing nothing is the design working. An `exit_status`
nobody recognises is either a bug here or an engine that has grown a
fourth ending.

## Why the translator holds state

An `event` document does not name its run. It names a descriptor, and only
the `descriptor` document carries `run_start`:

```
   start       uid ------------------+
   descriptor  uid, run_start -------+--> descriptor uid -> run uid
   event       descriptor -----------+
   stop        run_start
```

So `Translator` keeps a descriptor index and forgets a run's entries when
its `stop` arrives. It is still a pure core: what it holds is knowledge
the stream already delivered, not anything read from outside.

The spike this replaces tracked "the run we are currently walking"
instead, which held only because it replayed one scenario at a time.

## The fixture

`tests/documents.json` is captured output from a real engine driven through
seven scenarios: every ending, both interruptions, a plan that raises, and
one plan with real arguments. It arrived with the spike at
`spikes/bluesky_adapter/`, which wrote it, printed findings from it, and is
marked for deletion; the file moved here because the tests that assert
against it are not going anywhere.

Re-running the spike's `collect.py` overwrites it. That is deliberate: a
capture from a newer engine that changes an assertion is the signal worth
having, and the diff is the finding.

## Configuring it

```toml
[aroc]
base_url = "https://aroc.example"
token = "..."
external_ref_scheme = "engine-run-uid"

[plans]
count = "01a0ba64-8f95-7ad1-a7a7-44124ff3afd5"
```

The plan map is the interesting part, and it is here rather than in AROC
on purpose. AROC identifies a plan by id; a document carries only a name;
and two AROC plans may legitimately answer to one name, so turning a name
into an id depends on which installation this reporter serves. AROC does
not know that and nothing on the two records would tell them apart.

The cost is real: an operator who authors a new plan must add it here too,
and until they do, runs of it are refused. That is loud, which is the
trade against AROC guessing by recency and recording runs against whatever
it picked.

Everything is checked at load. A malformed plan id, a base URL that is not
one, a blank token: all refuse to start rather than failing on the first
run of that plan at whatever hour that is.

## Running it

```sh
uv sync
uv run pytest -q
uv run ruff check src tests && uv run ruff format --check src tests
uv run pyright src tests
```

Or from the repository root, where `make lint`, `make typecheck` and
`make test` cover this project and `apps/api` together.

## What is missing

| Piece | Waiting on |
| --- | --- |
| `session.py`, `__main__.py` | How this subscribes to an engine. |
| The checkpoint | The same decision. A direct subscription means a file here; a broker in between means a consumer-group offset and no file. |
| An identity to run as | A deployment. It is an actor in Access, and the grant list is recorded in the spike's `FINDINGS.md` section 5. It must **not** be granted `DefinePlan`: an adapter cannot honestly author a plan, and withholding the grant makes that a refusal at the boundary rather than a sentence in a document. |

Delivery is at-least-once in every design above, and safe because
`report_run` sends an idempotency key that `idempotency_key_for` derives
from the engine's own run id. A restarted reporter recomputes it having
persisted nothing, so a redelivered start returns the first run's id
instead of recording a second one.

One gap is open and worth naming, because the tests do not close it. They
assert the requests the client builds, not that AROC's routes accept them:
reading AROC's OpenAPI document would mean importing `aroc` here, which
would put the model in this project's environment and end the separation
above. So a route rename fails in `apps/api`'s own path pin, and whoever
does it has to look for callers. Closing it properly needs one end-to-end
run, which needs `session.py`.
