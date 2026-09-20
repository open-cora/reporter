# Reporter

Turns one engine's document stream into AROC's run commands.

**Runs, against a live engine.** `python -m reporter --subscribe` reads
documents off a real engine's 0MQ stream and reports the runs to AROC, and
it has. It also replays a capture, which is how it is tested without a
beamline. What is still missing is durability: see
[What is missing](#what-is-missing).

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

                              session.py joins them, and decides
                              what to do with a no
```

`Session.handle(name, document)` returns one of five outcomes, and the
split is by what a caller should do rather than by what happened:

```
   Recorded    a run is in AROC that was not
   Moved       a run changed state
   Unchanged   AROC declined; the run is not where the document
               expects it to be. a redelivery, almost always
   Skipped     the document said nothing about a run's life
   Held        it said something and could not be acted on
```

Advance past all five: every one is settled, so sending the document again
gets the same answer. Only `Held` is worth waking somebody. A refusal that
*could* pass later, a 429 or a 5xx, raises instead of returning, so a
caller that ignores outcomes cannot accidentally skip past one.

That is also why the checkpoint is the caller's. An outcome means the
document is finished with; an exception means ask again.

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

## Two ways to run it, and the same code either way

**Beside the engine, reading its published stream.** The engine publishes
to a 0MQ proxy, this connects to the other side of it, and the two know
nothing about each other beyond an address.

```
   engine  ---->  0MQ proxy  ---->  python -m reporter --subscribe  ---->  AROC
                      |
                      +---->  whatever else wants the documents
```

Preferred where there is a proxy, because it survives the engine
restarting, it lets more than one thing read the stream, and a bug in here
cannot take a scan down.

**Inside the engine's process.** `Relay.submit` is already the callback a
subscription wants, so there is nothing to build and nothing to configure
past the file below:

```python
from pathlib import Path
import httpx
from reporter import ArocClient, Relay, Session, load
from reporter.__main__ import documents_into

config = load(Path("reporter.toml"))
session = Session(ArocClient(httpx.Client(timeout=10), config), config)
relay = Relay(documents_into(session), print)
relay.start()

RE.subscribe(relay.submit)
```

That is the whole integration. `documents_into` is the only line that
names an engine: it puts this engine's translator in front of a `Session`
that knows nothing but AROC. A different engine composes its own
translator the same way and reuses everything under it. `submit` queues and returns in microseconds
and a worker thread does the talking, so a scan never waits on AROC even
though this is running inside it.

**What both have in common** is that a publisher drops what it sends while
nothing is listening. Start the reporter before the engine, not after.

### The stream is msgpack, and this refuses pickle

A publisher serializes with `pickle` unless it is told otherwise, and a
subscriber that went along with that would run whatever code reached the
port. So construct the publisher to match:

```python
import msgpack
from bluesky.callbacks.zmq import Publisher

RE.subscribe(Publisher("127.0.0.1:5567", serializer=msgpack.dumps))
```

A frame this cannot read stops the run rather than being skipped, with one
line naming the cause and exit 2. Every frame on a stream is encoded the
same way, so one unreadable frame means all of them, and carrying on would
drop every run on that stream while looking like a reporter that was
working.

Nothing here imports the engine's library to read its frames. The wire is
a prefix, a document name and a msgpack payload separated by single
spaces, which is the whole protocol, and reading it through the engine's
own package would drag the engine in as a dependency of the thing whose
claim is that it is not the engine.

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
uv run ruff check src tests typings && uv run ruff format --check src tests typings
uv run pyright src tests
```

Or from the repository root, where `make lint`, `make typecheck` and
`make test` cover this project and `apps/api` together.

## What is missing

| Piece | Waiting on |
| --- | --- |
| Durability | A transport that keeps a log. Documents live in the relay's queue and nowhere else, and 0MQ publish and subscribe has nothing behind it to ask again, so a document published while this is down was never published as far as this is concerned. At-most-once, known rather than accidental. |
| The checkpoint | The same thing. There is nothing to check point against: an offset is only meaningful over a transport that can be rewound to one. A broker in between gives both at once, and this becomes one of its consumers. |
| Anything other than AROC wanting these documents | Which is the question that decides the two rows above. If something else wants them, a broker is already justified and durability arrives with it. If not, this is the deployment and the gap is a cost somebody has to accept out loud. |
| An identity to run as | A deployment. It is an actor in Access, and the grant list is recorded in the spike's `FINDINGS.md` section 5. It must **not** be granted `DefinePlan`: an adapter cannot honestly author a plan, and withholding the grant makes that a refusal at the boundary rather than a sentence in a document. |

Redelivery is safe, whatever the transport turns out to be, because
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

## Proving it, end to end

Two demonstrations, and neither is a test double. The first has a real
engine in it.

### An engine nobody captured

Four processes, and every one of them real:

```sh
# 1. an AROC with no database
cd apps/api && APP_ENV=test uv run uvicorn aroc.api.main:app --port 8077

# 2. author the plans, as an operator would. the reporter cannot: it is
#    not granted DefinePlan, and could not derive a correct schema from
#    one invocation if it were. put the ids it returns in reporter.toml.
curl -X POST http://127.0.0.1:8077/plans -H 'content-type: application/json' \
  -d '{"name":"count","parameters_schema":{...}}'

# 3. a proxy for the engine to publish to
python -c "from bluesky.callbacks.zmq import Proxy; Proxy(5567, 5568).start()"

# 4. the reporter, before the engine, because a publisher drops what it
#    sends while nothing is listening
cd apps/reporter && uv run python -m reporter \
  --config reporter.toml --subscribe tcp://127.0.0.1:5568
```

Then, in an engine wired to that proxy:

```python
import msgpack
from bluesky.callbacks.zmq import Publisher
from bluesky.plans import count
from ophyd.sim import det

RE.subscribe(Publisher("127.0.0.1:5567", serializer=msgpack.dumps))
RE(count([det], num=3))
```

Stop the reporter, and the six documents that scan emitted come out as:

```
   stopping, and finishing what is already queued
     Moved        1        the stop document
     Recorded     1        the start document
     Skipped      4        a descriptor and three readings
```

and `GET /runs` holds a Completed run carrying the engine's own uid. No
capture file was involved at any point.

Stopping is SIGTERM as well as Ctrl-C, and both drain what the relay is
still holding before the process goes.

### A capture, which needs no beamline

The same command with `--replay tests/documents.json` runs the seven
captured scenarios:

```
   Moved        12
   Recorded      7
   Skipped      10
```

Run it a second time and it prints this instead, with AROC still holding
seven runs rather than fourteen:

```
   Recorded      7      the idempotency key returned the first run's id
   Skipped      10
   Unchanged    12      the transitions had already happened
```

Which is the redelivery gap closed, demonstrated rather than argued. A
wrong plan id in the config exits 2 before anything is sent, and so does a
publisher this cannot decode.
