# Reporter

Turns one engine's document stream into AROC's run commands, and says
where the data those runs produced is being kept.

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

The package is in two halves that do not import each other, joined in one
named place. A second engine replaces the left column and reuses the
right, which is a claim `tests/test_the_halves_stay_apart.py` enforces
rather than one this paragraph makes.

```
   reads one engine            the vocabulary          talks to AROC
   ----------------            --------------          -------------
   sources.py                                          client.py
     a live 0MQ stream                                   report_run
     or a capture                                        move_run
        |                                                find_run
        v                                                plan_exists
   translate.py  ---------->  intents.py  <----------  session.py
     start        ---->         ReportRun    ---->       POST /runs
     event(pause) ---->         Transition   ---->       POST /runs/{id}/pause
     stop         ---->         Transition   ---->       POST /runs/{id}/complete
     descriptor   ---->         Ignored                (nothing is sent)
     exit_status? ---->         Unmappable             (nothing is sent, loudly)
                                                          |
                                             stores.py <--+  on an ending
                                               locate(uid)
                                                  |
                                                  +---->    POST /datasets
                                                          |
                               outcomes.py  <-------------+
                                 Recorded Moved Kept
                                 Unchanged Skipped Held

                    wire.py   documents_into(session)
                              the only module that names both halves
```

`stores.py` is the third outside system and sits on neither side. The two
outward halves differ in direction: an engine pushes, so its translator is
called from `wire`, above the session; a store is asked, so its lookup is
called from inside the session, below it. What the session names is a
Protocol, so a different store is an implementation swapped at the
entrypoint.

`relay.py` sits in front of all of it with a queue and a worker thread, so
the engine's own thread never waits on a network. It takes a function
rather than a session, because a queue and a retry policy are the same
whatever is behind them.

The split was not designed. It was found by driving a second engine in
`spikes/tomoscan_adapter/`, whose stream has no documents in it at all,
and discovering that the only thing coupling the right column to the left
was a function signature.

## Two bounded contexts, one process

A stop means two things now: the run finished, and the data it produced
exists somewhere. So an ending asks the store where, and reports both.

```
   engine  --+
             +-->  [ this reporter ]  -->  Execution   POST /runs/{id}/complete
   store   --+                        -->  Custody     POST /datasets
```

One process rather than two, because the two are joined by an id. A
dataset cites a run by AROC's id for it, and resolving the engine's uid to
that id is what this reporter already does for a transition. Split them
and the second process is racing the first for the record it needs.

**The dataset leg is optional.** No `[store]` table means no lookup, no
`POST /datasets`, and everything else exactly as before. That is a
deployment rather than a degraded one: a facility whose engine writes
somewhere this cannot see should record runs and say nothing about data.

**`Kept` replaces `Moved` for an ending** rather than arriving beside it,
because one intent gets one outcome. The cost is worth knowing before
reading a tally: when the run moves and the dataset cannot be registered,
the single outcome has to be `Held`, so a session run against a store that
is down reports no `Moved` at all even though every run moved. The moves
are in AROC either way and `Held` names the store as it happens. It is the
summary that misleads, not the record.

**Subscribe the writer first.** Both callbacks run on the engine's thread
in the order they were subscribed, so a reporter subscribed after the
writer sees a finished node every time, with no retry and no sleep.
Subscribed before it, the node exists without its ending, the registration
still happens, and AROC stamps the arrival instead. That guarantee is
in-process only: over a message bus this really is a race.

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

## The two fixtures

`tests/documents.json` is captured output from a real engine driven through
seven scenarios: every ending, both interruptions, a plan that raises, and
one plan with real arguments. `tests/nodes.json` is the same idea against a
real store: four scenarios written by the writer a deployment would use,
then interrogated from outside the way this package has to.

Neither is written by hand and neither can be regenerated from here. The
two collectors live in `spikes/`, because they import an engine and a store
and this package depends on neither:

```
   spikes/bluesky_adapter/collect.py  ---->  tests/documents.json
   spikes/tiled_adapter/collect.py    ---->  tests/nodes.json
```

Re-running either overwrites its capture, which is deliberate and is the
closest thing here to a test of the real thing. Ids and timestamps change
every run, so the diff is mostly noise; what to read is whether the suite
still passes. The assertions are written against the structural claims, so
an engine or a store that changed one turns a test red with a message
naming it, and that message is the finding.

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
from reporter import ArocClient, Relay, Session, documents_into, load

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

[store]
base_url = "https://store.example"
root = "raw"
external_ref_scheme = "tiled-node-path"
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

`[store]` is the optional table and leaving it out switches the dataset
leg off. Three things about it are worth knowing.

`root` is where the writer points, and it is configuration because it
cannot be discovered: a search does not descend, so a reporter cannot find
a run by uid without already knowing where to look. A misconfigured root
finds nothing rather than finding the wrong thing, which is the better
failure.

`external_ref_scheme` is a second one and not the same as the one above.
That one names the vocabulary an engine's run ids belong to; this one
names the vocabulary a store's addresses belong to. Setting them to one
string would be claiming two kinds of reference are interchangeable.

There is no token for the store. Nothing has needed one, and adding the
field before something asks would be inventing an auth scheme on a store's
behalf.

Everything is checked at load. A malformed plan id, a base URL that is not
one, a blank token, a `[store]` table that is present and wrong: all
refuse to start rather than failing on the first run of that plan at
whatever hour that is. A configured store is also reached for once before
the first document moves, because a reporter that records every run and
quietly files no data is worse than one that will not start.

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
| An identity to run as | A deployment. It is an actor in Access, and the two spikes each record the grants their half needs: `spikes/bluesky_adapter/FINDINGS.md` section 5 for the runs, `spikes/tiled_adapter/FINDINGS.md` section 7 for the datasets. A process carrying both legs runs as one actor holding the union. It must **not** be granted `DefinePlan`: an adapter cannot honestly author a plan, and withholding the grant makes that a refusal at the boundary rather than a sentence in a document. |
| A token for the store | Something asking for one. The lookup sends no credential, so this works against a store that does not want one and nothing else. |

Redelivery is safe, whatever the transport turns out to be, because both
writes send an idempotency key derived from something this can recompute
after a restart having persisted nothing. A redelivered start returns the
first run's id rather than recording a second run.

The two keys name different things, deliberately. `idempotency_key_for`
names the run, because a start is identified by the run it began.
`dataset_key_for` names the store's address, because a dataset is
identified by where the data is. They are the same string today and they
part company the day a run produces two datasets: keyed on the run, both
registrations would carry one note and the second would come back holding
the first one's id, silently. AROC refused to derive a dataset's identity
from its run for exactly that reason, and a key naming the run would put
the constraint back somewhere no migration announces.

One gap is open and worth naming, because the tests do not close it. They
assert the requests the client builds, not that AROC's routes accept them:
reading AROC's OpenAPI document would mean importing `aroc` here, which
would put the model in this project's environment and end the separation
above. So a route rename fails in `apps/api`'s own path pin, and whoever
does it has to look for callers. What closes it is the run below, which
needs no test double at any point.

The store half has the same gap and one fewer worry, for the reason
[The two fixtures](#the-two-fixtures) gives: what it is checked against is
real output from a real store rather than a shape imagined here.

## Proving it, end to end

Two demonstrations, and neither is a test double. The first has a real
engine in it.

**Both are runs of the engine leg only.** Neither has had a store in it,
so the numbers below carry no `Kept`. The dataset leg is covered by tests
against real captured store output and has not been through this section,
which is the difference between checked and demonstrated, and the reason
this paragraph is here rather than a third heading with plausible figures
under it.

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
