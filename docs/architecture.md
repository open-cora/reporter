# Architecture

*How this package is put together, the one split everything else follows from,
and how any of it is checked without a beamline.*

[Reporting](reporting.md) says what a reporter does, in no code at all. This
page is the same thing with the names on it, for somebody about to change one.

## The rule

**The core knows no adapter, and an adapter knows one outside system.**

Five modules import the standard library and each other: `seams`, `intents`,
`outcomes`, `session` and `relay`. Everything that knows an engine's grammar, a
store's API or the record's HTTP lives under `reporter/adapters/`, and one
module names both sides.

`tests/test_the_core_names_no_seam.py` holds that, and pins the membership on
both sides: `EXPECTED_CORE_MODULES` is five and `EXPECTED_ADAPTERS` is six, so
neither list can quietly stop being the list. It also refuses an engine
library, a transport library or a store library imported anywhere above the
adapters.

## The pieces

```
   the core: five modules, the standard library, and each other
   ---------------------------------------------------------------------
   seams.py                    intents.py           outcomes.py
     Delivering  what arrives    ReportStepRun        Relayed   Kept
     Reporting   file a report   RegisterDataset      Unchanged
     Filing      file a dataset  Ignored              Skipped   Held
     Locating    ask a store     Unmappable

              \                      |                     /
               +-------> session.py <+--------------------+
               |           one intent at a time, and what
               |           to do with a no
               |
               +-------> relay.py
                           a queue and a worker thread

   the adapters: one outside system each, six of them
   ---------------------------------------------------------------------
   knows one engine's grammar       knows the record, or the store
   --------------------------       -------------------------------
   bluesky_documents.py             keeper_http.py   Reporting, Filing
   tomoscan_records.py              store_http.py    Locating
   zmq_subscription.py
   capture_replay.py

   in between
   ---------------------------------------------------------------------
   config.py      the settings
   __main__.py    the only module that names both columns
```

A second engine is a sibling file in the left column and nothing else. It
reuses `intents`, `session`, `outcomes` and the whole right column unchanged,
which is what makes supporting one a translation rather than a rewrite.

**The split was found, not designed.** It came out of driving a second engine
whose stream has no documents in it at all, and discovering that the only thing
coupling the right column to the left was a function signature.

## One delivery, in code

```
   a source hands over a Delivery          (name, payload)
     from_subscription(...)   a live engine over its socket
     from_tomoscan(prefix)    a scan server, polled over its records
     from_capture(path)       a recording, which is how this is tested

   Relay.submit(name, payload)
     queues and returns in microseconds, so the engine's own thread
     never waits on a network; a worker thread does the talking
         |
         v
   a Handle, built by the engine's own adapter
     documents_into(session)  one engine's grammar -> Intent
     records_into(session)    another engine's    -> Intent
         |
         |   ReportStepRun    -> Session reports it
         |   RegisterDataset  -> Session asks Locating, then files
         |   Ignored          -> nothing is sent
         |   Unmappable       -> nothing is sent, loudly
         v
   Session acts on one intent
     Reporting.record(intent)                        into Execution
     Locating.locate(ref) then Filing.record(intent) into Custody
         |
         v
   an Outcome:  Relayed | Kept | Unchanged | Skipped | Held
```

**Translation lives in the adapter, not in the core.** A start, a descriptor,
an event and a stop are one engine's grammar, and the two-hop lookup between
them is that grammar's problem. What crosses into the core is an `Intent`,
which no engine's vocabulary reaches.

**An adapter can be pure, and one is.** `bluesky_documents` has no network, no
clock and no configuration: documents in, intents out. It is filed as an
adapter because of what it knows rather than what it touches, and that is the
rule for the directory. It is also what lets every result obtained by driving a
real engine be re-asserted against the captured file with no engine and no
keeper running.

## What each decision cost

**The store is neither half, and sits between them.** The direction is why: an
engine pushes, so its translator is called from above the session, and a store
is asked, so its lookup is called from inside the session, below it. What the
session names is a capability, so a different store is swapped in at the
entrypoint.

**The dataset leg switches off by an absence, not a flag.** A deployment with
no store has no `Filing` and no `Locating`, and `Session` reads the two
absences as this reporter not doing that. It used to read a configuration table
instead, and ask it again at each of the three places the answer mattered.
There is nothing left to disagree with itself: a session that cannot file was
not given the capability, and the pair is built together or not at all.

**Three kinds of failure and no status codes.** An adapter raises
`UnavailableError`, `RefusedError` or `DisagreedError`, and nothing else. Those
are the only distinctions anything above needs, and a status code reaching the
core would be the record's wire format leaking into a module that must not know
there is a wire.

**The queue takes a callable, not a session.** `Relay` is handed a `Handle`,
because a queue and a retry policy are the same whatever is behind them.

**One path, with the verb in the body.** Every report goes to one address, with
which kind of report it is in the body. That is the record's choice made for
this caller: a reporter turns each delivery into whichever kind it is, so an
address per kind would make it build a URL by lookup.

## How this is checked without a beamline

Two recordings, both captured from the real thing rather than imagined here.

```
   scripts/collect_documents.py  ---->  tests/documents.json
   scripts/collect_nodes.py      ---->  tests/nodes.json
```

The first is output from a real engine driven through seven scenarios: every
ending, both interruptions, a plan that raises, and one with real arguments.
The second is a real store, written by the writer a deployment would use, then
interrogated from outside the way this package has to.

Neither is written by hand, and the collectors live outside every lane because
they import an engine and a store this package does not depend on. Both are
re-recordable with `make refresh-captures`.

Re-running one overwrites it, which is deliberate and is the closest thing here
to a test of the real thing. Ids and times change every run, so the diff is
mostly noise. What to read is whether the suite still passes: the checks are
written against the structural claims, so an engine or a store that changed one
turns a test red with a message naming it, and that message is the finding.

## What is deliberately not here

**No engine library.** The wire is a prefix, a message name and a packed
payload separated by single spaces, which is the whole protocol. Reading it
through the engine's own package would drag the engine in as a dependency of
the thing whose claim is that it is not the engine.

**No interpretation.** Nothing opens a payload to see what it means.

**No durability.** Deliveries live in the queue and nowhere else. What that
costs is stated in the README's list of what is missing rather than hidden.

**No memory of a run.** `Session` used to hold a map from an engine's own
reference to the record the keeper held for it. The two ids now arrive in the
engine's own metadata on the opening message, so there is nothing to remember
and nothing to look up.
