# Reporter

*Passes on what it was handed, and reads none of it.*

**The reporter is how results get back.** It reads the stream of messages an
acquisition engine produces during a run, turns each one into a report about the
step it belongs to, and says where the data that step produced is stored. It runs
next to the engine, because that is where the messages are, and everything it
files it files over HTTP.

**It invents nothing.** Every report names work that was written down before the
engine was ever asked to do it: the job was put together, it was approved, and
whatever ran it carried the step's ids into the engine's own metadata. So every
request names something that already exists.

A message that refers to no such work is skipped rather than turned into a new
record. It is a scan somebody ran by hand, it is real work, and there is nothing
here to attach it to. Skipped quietly, because complaining about every message of
every hand-run scan teaches people to ignore the channel. Nothing is destroyed,
and a shape for reporting it could be added later.

**It reads none of it.** No message is opened to see what it means, no number is
checked, and nothing is judged. What arrives is passed on word for word, and
something further out decides what it was.

## Why this is a program of its own

While somebody is watching a run, getting results back is a convenience. The
moment work runs unattended it is the only thing making what happened visible to
whatever decides what happens next, and it has to keep working while nobody is
watching it either.

That is why it sits next to the engine rather than inside it. A bug here cannot
take a scan down, the engine never waits on the network, and more than one thing
can read the same stream.

It is also why supporting a second engine means writing a translation rather than
a rewrite. The half that reads an engine and the half that files a report do not
know about each other, so a new engine costs only the vocabulary it speaks.

And it is why this may name a particular engine on most of its pages when the
record it files to may not. Which engine a site runs is that site's business, and
a rule stated for one reads as a rule derived from one. Being a program of its
own is how that stays true without an exception.

## What it will not claim

**That a run was any good.** Everything it files is something it was told, not
something it checked. An engine reporting success is a claim, it travels as one,
and nothing here dresses it up as a finding.

**That nothing was lost.** Messages are held in memory between arriving and being
filed, and a publisher drops what it sends while nobody is listening, so a
message sent while this is down was never sent as far as this is concerned. At
most once, known rather than accidental, and named in
[What is missing](#what-is-missing) rather than implied.

## Where it stands today

`python -m reporter --subscribe` reads messages off a real engine's stream and
reports them, and it has. It also replays a recording, which is how it is tested
without a beamline. What is still missing is durability.

## Reading further

The detail that used to sit here lives on the site, where the nav carries it and
a broken cross-link fails the build.

| To read about | Page |
| --- | --- |
| Running one, configuring it, the stream format | [Running one](docs/running.md) |
| What it reports, and why it remembers | [Reporting](docs/reporting.md) |
| The two contexts, and how this is checked without a beamline | [Architecture](docs/architecture.md) |
| What travels between this and the keeper | [Contract](docs/client-contract.md) |
| The words, used the same way in code and prose | [Glossary](docs/glossary.md) |

In short: `uv sync --all-extras` then `uv run pytest -q`. Every test runs against
a recorded capture, so the suite needs no engine, no store and no beamline.

## What is missing

| Piece | Waiting on |
| --- | --- |
| Durability | A transport that keeps a log. Documents live in the relay's queue and nowhere else, and 0MQ publish and subscribe has nothing behind it to ask again, so a document published while this is down was never published as far as this is concerned. At-most-once, known rather than accidental. |
| The checkpoint | The same thing. There is nothing to check point against: an offset is only meaningful over a transport that can be rewound to one. A broker in between gives both at once, and this becomes one of its consumers. |
| Anything other than the keeper wanting these documents | Which is the question that decides the two rows above. If something else wants them, a broker is already justified and durability arrives with it. If not, this is the deployment and the gap is a cost somebody has to accept out loud. |
| A reporter run against a live conducted scan | A sitting with a beamline. `conductor.adapters.bluesky_acquisition` now writes `keeper_execution_id` and `keeper_step_id` into every start document it opens under a dispatch, and both sides pin the spelling, so the contract this half states is performed. What has not happened is the two running against one engine at once. |
| An identity to run as | A deployment. It is an actor in Access, and the two spikes each record the grants their half needs: a spike, a spike for the datasets. A process carrying both legs runs as one actor holding the union. It must **not** be granted `DefineOperation` or `DefineProcedure`: an adapter cannot honestly author either, and withholding the grants makes that a refusal at the boundary rather than a sentence in a document. |
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
the first one's id, silently. The keeper refused to derive a dataset's identity
from its run for exactly that reason, and a key naming the run would put
the constraint back somewhere no migration announces.

One gap is open and worth naming, because the tests do not close it. They
assert the requests the client builds, not that the keeper's routes accept them:
reading the keeper's OpenAPI document would mean importing `keeper` here, which
would put the model in this project's environment and end the separation
above. So a route rename fails in the keeper's own path pin, and whoever
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
# 1. a keeper with no database
APP_ENV=test uv run uvicorn keeper.api.main:app --port 8077   # in the keeper's checkout

# 2. author the operations, as an operator would. the reporter cannot: it
#    is not granted DefineOperation, and could not derive a schema from
#    one invocation if it were. put the ids it returns in reporter.toml.
curl -X POST http://127.0.0.1:8077/operations -H 'content-type: application/json' \
  -d '{"name":"count","parameters_schema":{...}}'

# 3. a proxy for the engine to publish to
python -c "from bluesky.callbacks.zmq import Proxy; Proxy(5567, 5568).start()"

# 4. the reporter, before the engine, because a publisher drops what it
#    sends while nothing is listening
uv run python -m reporter \
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

Run it a second time and it prints this instead, with the keeper still holding
seven runs rather than fourteen:

```
   Recorded      7      the idempotency key returned the first run's id
   Skipped      10
   Unchanged    12      the transitions had already happened
```

Which is the redelivery gap closed, demonstrated rather than argued. A
wrong operation id in the config exits 2 before anything is sent, and so does a
publisher this cannot decode.

## Related projects

Published from the same development tree, and separate deployables on purpose.
Nothing here imports any of them and none of them imports this; the boundary is
the interpreter's rule rather than a convention.

| Project | Does |
| --- | --- |
| [keeper](https://github.com/open-cora/keeper) | Holds the record, and who may add to it |
| [conductor](https://github.com/open-cora/conductor) | Runs the work at the beamline |
| [thinker](https://github.com/open-cora/thinker) | Suggests what to run next |

## Where the code is developed

**This repository is what you deploy, install and cite.** It is one deployable,
versioned and released on its own, and it runs standalone: its own lockfile,
its own suite, its own site.

**Development happens in [open-cora/cora](https://github.com/open-cora/cora)**,
a tree holding this project and the three above side by side, from which each is extracted with
`git subtree` and its history intact. What is missing here is the other
projects, and the end-to-end tests that need more than one of them at once.

A change merged here would be overwritten by the next publish, so open an issue
or fork. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache-2.0. See [LICENSE](LICENSE).
