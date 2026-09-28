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
from reporter import KeeperClient, Relay, Session, documents_into, load

config = load(Path("reporter.toml"))
session = Session(KeeperClient(httpx.Client(timeout=10), config), config)
relay = Relay(documents_into(session), print)
relay.start()

RE.subscribe(relay.submit)
```

That is the whole integration. One line names an engine: it puts that engine's
translator in front of a session that knows nothing but the record. Submitting
queues and returns in microseconds and a worker thread does the talking, so a
scan never waits on the network even though this is running inside it.

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

Stopping the process prints a tally of what it did. Against a real engine
running one three-point count:

```
   Moved        1        the ending
   Recorded     1        the opening
   Skipped      4        a descriptor and three readings
```

Stopping drains whatever the queue is still holding before the process goes,
whether that is a polite stop or an interrupt.

Replaying the captured recording needs no beamline at all:

```sh
uv run python -m reporter --config reporter.toml --replay tests/documents.json
```

Run it a second time and the tally changes while the record still holds seven
runs rather than fourteen, because the keys sent with each write returned the
first run's id. That is redelivery being safe, demonstrated rather than argued.

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
