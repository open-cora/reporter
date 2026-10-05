# Reporter

*Passes on what it was handed, and reads none of it.*

**The reporter is how results get back.** It reads the stream of messages an
engine produces during a run, turns each one into a report about the
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
most once, known rather than accidental, and stated rather than implied.

## Where it stands today

Every seam here has an adapter written for it. Which of them a deployment
configures is a separate question, and it is the one that decides what that
deployment can do.

| Adapter | Seam | How far it has been taken |
| --- | --- | --- |
| `tomoscan_records` | where a scan is heard from | Watches a scan server's own records over Channel Access. This is what beamline deployments run, and conducted scans have been filed through it. |
| `zmq_subscription` | the same, over documents | Reads an engine's document stream. It has read a real engine and reported from it, but never one a conductor was driving. |
| `capture_replay` | the same, from a file | Replays a committed recording, which is how the suite runs with no engine, no store and no beamline. |
| `bluesky_documents` | translation behind the two above | Documents in, intents out. Pure, so every result from driving a real engine is re-asserted against the captured file with nothing running. |
| `keeper_http` | `Reporting`, `Filing`, `Cataloguing` | Writes what happened to the record. This is what beamline deployments run. |
| `dxchange_hdf5` | `Describing` | Opens the filed HDF5 and measures it, so a description tracks the file rather than restating the request. Beamline deployments run this. |
| `store_http` | `Locating` | Resolves a name to an address. No deployment configures a store, so this seam is empty everywhere and an address in the record is a path nothing resolves. |

So the records path is exercised end to end and the document path is not:
`zmq_subscription` has read a real engine, but no run has gone out of a
conductor and into it. What is still missing besides that is durability.

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

## What to know before running one

**No deployment configures a store, and the process needs an identity.** A
reporter is an actor in Access and its two legs need different grants: one set
for relaying documents, another for registering datasets. A process carrying
both runs as one actor holding the union. It must **not** be granted
`DefineOperation` or `DefineProcedure`: an adapter cannot honestly author
either, and withholding the grants makes that a refusal at the boundary rather
than a sentence in a document.

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

Two demonstrations that are real, and one that has not happened. Saying
which is which is the point of this section, and the reason there are no
plausible figures under a fourth heading.

### A capture, which needs no beamline

The committed recording is seven scenarios somebody ran by hand at a
beamline, with nothing dispatching them. No start document in it carries
the keeper's ids, so this reporter has no record to attach any of it to:

```sh
uv run python -m reporter --config reporter.toml --replay tests/documents.json
```

```
  Skipped      29
```

That is the whole output, and it is worth seeing once. The keeper was
never contacted: the run above used a base URL with nothing listening on
it and still exited 0, because every document translated to `Ignored`
before anything could be sent.

Work nobody dispatched being quiet rather than loud is the behaviour most
likely to look like a broken reporter, and it is the deliberate one. An
alert here would fire on every document of every scan run by hand at the
beamline, which teaches whoever is watching to stop reading the output,
and the `Held` channel rests on that not happening.

A publisher this cannot decode exits 2 rather than skipping the frame,
and so does a configuration that will not load. Both refuse before
anything is sent.

### A conducted scan over records, which runs at four beamlines

Records mode needs no proxy and no document stream. A TomoScan engine
publishes its own records, a conductor drives it, and this watches the
records go by:

```sh
uv run python -m reporter --config reporter.toml --records corasim2bmb:TomoScan:
```

What a finished scan leaves in the record is an address and, where a
`Describing` adapter is configured, a manifest of what is inside the file.
`dxchange_hdf5` opens the file and measures it, so the manifest tracks the
file rather than restating the request: ask for a different number of
angles and the extent of the angle dataset follows, which is the property
worth checking and the one a description copied from the dispatch would
fail.

Two things are wired here that are not wired everywhere. `Locating` has no
adapter configured, because these deployments have no data store, so the
address in the record is a path and nothing resolves it. And every engine
behind these four is a simulator serving records the deployment supplies
itself, so what this establishes is the recording path and not any
detector.

### A conducted scan over documents, which has not happened

A conducted scan is recorded at four beamlines through the records path,
which is the section above. Over documents there is no transcript, because
such a run needs four things at once: a keeper holding a dispatched
execution, a conductor claiming and driving it, a Bluesky engine that
conductor drives, and a proxy between that engine and this.
`conductor.adapters.bluesky_engine` writes `keeper_execution_id` and
`keeper_step_id` into the start document
of every run it opens under a dispatch, and this reporter reads them back,
and each side pins the two literals in a test naming the other. Both
halves are built and tested. They have not been run against one engine at
the same time.

What can be stated without that sitting is the wiring, which is checked
against real captured output rather than imagined:

```sh
# a proxy for the engine to publish to
python -c "from bluesky.callbacks.zmq import Proxy; Proxy(5567, 5568).start()"

# the reporter, before the engine, because a publisher drops what it
# sends while nothing is listening
uv run python -m reporter --config reporter.toml --subscribe tcp://127.0.0.1:5568
```

Then, in an engine wired to that proxy:

```python
import msgpack
from bluesky.callbacks.zmq import Publisher

RE.subscribe(Publisher("127.0.0.1:5567", serializer=msgpack.dumps))
```

The serializer is not optional. A publisher uses `pickle` unless told
otherwise, and a subscriber that went along with that would run whatever
code reached the port.

Stopping is SIGTERM as well as Ctrl-C, and both drain what the relay is
still holding before the process goes.

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
