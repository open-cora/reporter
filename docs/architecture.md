# Architecture

How this package is put together, and the one split everything else follows
from.

## The split

The package is in two halves that do not import each other, joined in one named
place.

```
   knows one engine           the vocabulary        knows the record
   ------------------         --------------        ----------------
   sources.py                                       client.py
     a live stream                                    file a report
     or a recording                                   file a dataset
        |
        v
   translate.py  -------->  intents.py  <--------  session.py
     start        ---->     report a run  ---->      it started
     pause        ---->     report a run  ---->      it paused
     stop         ---->     report a run  ---->      it finished
     descriptor   ---->     ignore it              (nothing is sent)
     no ids       ---->     ignore it              (nothing is sent)
     unknown      ---->     cannot map it          (nothing is sent, loudly)
                                                        |
                                           stores.py <--+  on an ending
                                             where is it
                                                |
                                                +---->   file a dataset
                                                        |
                             outcomes.py  <-------------+
                               relayed, kept, unchanged,
                               skipped, held

                  wire.py    the only module that names both halves
```

A second engine replaces the left column and reuses the right. That is what
makes supporting another engine a translation rather than a rewrite, and it is
checked by `tests/test_the_halves_stay_apart.py` rather than claimed here.

**The split was found, not designed.** It came out of driving a second engine
whose stream has no messages in it at all, and discovering that the only thing
coupling the right column to the left was a function signature.

## The third outside system, and why it sits differently

The store is neither half. It sits between them, and the direction is why: an
engine pushes, so its translator is called from above the session; a store is
asked, so its lookup is called from inside the session, below it. What the
session names is an interface, so a different store is swapped in at the entry
point.

## The queue in front

`relay.py` sits in front of all of it with a queue and a worker thread, so the
engine's own thread never waits on a network. Submitting queues and returns in
microseconds; the worker does the talking.

It takes a function rather than a session, because a queue and a retry policy
are the same whatever is behind them.

## One path, with the verb in the body

Every report goes to one address, with which kind of report it is in the body.
That is the record's choice made for this caller: a reporter turns each message
into whichever of several reports it is, so an address per kind would make it
build a URL by lookup.

## How this is checked without a beamline

Two recordings, both captured from the real thing rather than imagined here.

```
   scripts/collect_documents.py  ---->  tests/documents.json
   scripts/collect_nodes.py      ---->  tests/nodes.json
```

The first is output from a real engine driven through seven scenarios: every
ending, both interruptions, a plan that raises, and one with real arguments. The
second is a real store, written by the writer a deployment would use, then
interrogated from outside the way this package has to.

Neither is written by hand, and the collectors live outside every lane because
they import an engine and a store that this package does not depend on. Both are
re-recordable with `make refresh-captures`.

Re-running one overwrites it, which is deliberate and is the closest thing here
to a test of the real thing. Ids and times change every run, so the diff is
mostly noise. What to read is whether the suite still passes: the checks are
written against the structural claims, so an engine or a store that changed one
turns a test red with a message naming it, and that message is the finding.

## What is deliberately not here

**No engine library.** The wire is a prefix, a message name and a packed
payload separated by single spaces, which is the whole protocol. Reading it
through the engine's own package would drag the engine in as a dependency of the
thing whose claim is that it is not the engine.

**No interpretation.** Nothing opens a payload to see what it means.

**No durability.** Messages live in the queue and nowhere else. What that costs
is stated in the README's list of what is missing rather than hidden.
