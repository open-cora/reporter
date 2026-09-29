# Running one

This page is for whoever installs a reporter beside an engine.

## Two ways, and the same code either way

**Beside the engine, reading its published stream.** The engine publishes to a
proxy, this connects to the other side of it, and the two know nothing about
each other beyond an address.

```
   engine  ---->  proxy  ---->  python -m reporter --subscribe  ---->  record
                    |
                    +---->  whatever else wants the messages
```

Preferred wherever there is a proxy. It survives the engine restarting, it lets
more than one thing read the stream, and a bug in the reporter cannot take a
scan down.

**Inside the engine's process.** The relay's submit is already the callback a
subscription wants, so there is nothing to build:

```python
from pathlib import Path
import httpx
from reporter import Relay, Session, load
from reporter.adapters.bluesky_documents import documents_into
from reporter.adapters.keeper_http import HttpReporting

config = load(Path("reporter.toml"))
http = httpx.Client(timeout=10)
session = Session(HttpReporting(http, config.base_url, config.token))
relay = Relay(documents_into(session), print)
relay.start()

RE.subscribe(relay.submit)
```

That is the whole integration. Two lines name something outside: one picks the
engine whose documents these are, the other picks how the record is reached.
Everything between them is a session that knows neither. Submitting queues and
returns in microseconds and a worker thread does the talking, so a scan never
waits on the network even though this is running inside it.

The session above records runs and says nothing about data, because it was
given no `Filing` and no `Locating`. Adding the dataset leg means building
both from the `[store]` table and passing them, which is what `__main__` does:

```python
from reporter.adapters.keeper_http import HttpFiling
from reporter.adapters.store_http import HttpLocating

store = config.store
session = Session(
    HttpReporting(http, config.base_url, config.token),
    HttpFiling(http, config.base_url, config.token, store.external_ref_scheme),
    HttpLocating(http, store.base_url, store.root),
)
```

**Start the reporter before the engine, either way.** A publisher drops what it
sends while nothing is listening.

## The stream must not be pickle

A publisher serializes with pickle unless told otherwise, and a subscriber that
went along with that would run whatever code reached the port. So build the
publisher to match:

```python
import msgpack
from bluesky.callbacks.zmq import Publisher

RE.subscribe(Publisher("127.0.0.1:5567", serializer=msgpack.dumps))
```

A frame the reporter cannot read stops the run rather than being skipped, with
one line naming the cause and a non-zero exit. Every frame on a stream is
encoded the same way, so one unreadable frame means all of them, and carrying on
would drop every run on that stream while looking like a reporter that was
working.

## Configuring one

```toml
[keeper]
base_url = "https://keeper.example"
token = "..."

[store]
base_url = "https://store.example"
root = "raw"
external_ref_scheme = "tiled-node-path"
```

Two settings and an optional section.

**The store section is what switches the dataset half on.** Leave it out and the
reporter files runs and says nothing about data.

**`root` is where the writer points.** It is configuration because it cannot be
discovered: a search does not descend, so a reporter cannot find a run by id
without already knowing where to look. A wrong root finds nothing rather than
finding the wrong thing, which is the better failure.

**`external_ref_scheme`** names the vocabulary the store's addresses belong to.
It sits on the store section because it describes the store: a deployment that
changes where its data is kept changes both together.

There is no token for the store. Nothing has needed one, and adding the field
before something asks would be inventing an authentication scheme on a store's
behalf.

**Everything is checked at startup.** A base URL that is not one, a blank token,
a store section that is present and wrong: all refuse to start rather than
failing on the first scan of the day. A configured store is also reached for once
before the first message moves, because a reporter that files every report and
quietly saves no data is worse than one that will not start.

A file with an old `[plans]` section still in it loads. Nothing reads it, and
refusing it would turn an upgrade into an outage over a setting that does
nothing.

## Watching it work

Stopping the process prints a tally of what it did, counted by outcome:
`Relayed`, `Kept`, `Unchanged`, `Skipped` and `Held`. Stopping drains
whatever the queue is still holding before the process goes, whether that is
a polite stop or an interrupt.

Replaying the captured recording needs no beamline at all:

```sh
uv run python -m reporter --config reporter.toml --replay tests/documents.json
```

```
  Skipped      29
```

Every document in that recording was a scan somebody ran by hand, so none of
them carries the ids a dispatch writes and there is no record to attach any
of it to. The keeper is not contacted at all, which is why the command above
exits 0 even with nothing listening at the configured address. A tally of
nothing but `Skipped` against a live stream means the same thing: whatever is
publishing was not dispatched by the keeper.

`Held` is the line worth watching. It is printed as it happens rather than at
the end, because a process that reports it on shutdown reports it to nobody,
and it is the only outcome that makes the exit status non-zero.

## Running the tests

```sh
uv sync
uv run pytest -q
uv run ruff check src tests typings && uv run ruff format --check src tests typings
uv run pyright src tests
```

No beamline, no engine and no store required: the suite runs against two
recordings captured from the real things. See
[Architecture](architecture.md#how-this-is-checked-without-a-beamline).
