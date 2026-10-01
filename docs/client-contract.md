# Client contract

*How the keeper's peer clients name the same work, and what that name is not.*

This page exists in all three projects, word for word. They share no code
and ship separately, so the agreement is prose in each of them rather than a
package none of them wants to depend on. What holds the copies honest is not
this page: it is that the two metadata keys are pinned to literals in a test
on each side, and renaming one fails the other.

That is worth reading narrowly. A test proves the three copies identical, and
a test proves each side spells the two keys the same way. Nothing compares this
page against the code, so everything below that is not a key spelling is prose
somebody has to keep true by hand.

The keeper has two clients that are not part of it. The reporter watches an engine and records what it sees. The conductor composes a procedure and drives a beamline through it, holding a device claim for each step. Neither imports `keeper`, nothing in the keeper imports either, and they do not import each other.

They nevertheless talk about the same work, so they need one answer to "which run is that". This page is that answer. It is prose rather than a shared package on purpose: a third project existing to hold a string and four HTTP rules would cost more than the duplication it saves.

## One run has two names

An engine mints its own identifier for every run it opens. The keeper's names exist earlier: the execution and the step are written when the procedure is dispatched, before anything is asked of an engine.

So one run carries both:

| | minted by | known at | spelled |
| --- | --- | --- | --- |
| run uid | the engine | the moment the run opens | the engine's own word for it |
| execution and step ids | the keeper | at dispatch, before the operation is submitted | `keeper_execution_id`, `keeper_step_id` |

An earlier draft of this table named a single key holding one reference the driver minted, and no such key exists. Two travel, because a step is an entity inside the Execution aggregate rather than a stream of its own, so naming one means naming the execution around it.

## The keeper reference travels outward, and the engine's uid comes back

The keeper composes the work and dispatches it, so the ids exist before an engine is asked for anything. Whatever drives an execution carries the step's execution id and step id out to the engine, and whatever watches that engine reads them back.

**The two spellings above are the contract.** Each side pins both literals in a test that names the other, which is the only part of this page a rename cannot get past.

That means a keeper identifier sits in somebody else's records, which is the one place in this tree where that happens. It was weighed rather than assumed. What it buys is that the reporter resolves nothing, carries no plan map, and cannot join the wrong record; what it costs is that a document with no such reference cannot be attributed at all, and is skipped.

The engine's own uid travels in the other direction, as a step's `engine_reference`. It is a correlation hint rather than a key: nothing checks that such a run exists, and nothing could, because whatever watches the engine records it on its own schedule.

### The pair travels by two roads, because there are two kinds of engine

```
   an engine in the driver's process     the pair goes in as metadata at
   that publishes documents              the call, and comes back out of
                                         the start document

   an engine that is a service on        the pair is written into the
   the control network                   service's own records, and read
                                         back from them
```

The contract is the pair and its spelling. Which road it takes is the adapter's business, and a client that assumed the first road is the only one would miss every run driven over the second.

Both are implemented. `conductor.adapters.bluesky_engine` writes the pair into the start document of every run it opens under a dispatch, and `reporter.adapters.bluesky_documents` reads it back; `conductor.adapters.tomoscan_engine` writes the same two ids into a scan server's records and reads them back from there. A run opened outside a dispatch carries neither id, which is how a scan somebody ran by hand stays distinguishable from work this system is owed a report on.

## Two settings that have to agree

The scheme is a word, and two deployments have to pick the same one.

- The reporter reads `external_ref_scheme` from the `[store]` table of its TOML configuration and sends it with every dataset it registers. What a given deployment settled on is written down in its beamline descriptor.
- The conductor registers no datasets and so names no scheme. It did once, for engines that answered with a location, and the seam was removed because reading an address needs no claim and no walk: whatever watches such an engine reads the same value from the same place.
- Anything that later resolves a dataset's address must read it under that same word.

Nothing checks this. Two deployments configured differently file data under two vocabularies that look alike and are not, and nothing in the keeper can tell them apart, because the scheme names a vocabulary rather than an instance.

## What this page does not promise

**The metadata is writable by anyone who can start a plan.** The engine is outside the keeper, so the two ids can be set by hand, copied between runs, or left off. What that buys an attacker is narrower than it was: the ids name records the keeper already wrote, so a forged pair moves an existing step rather than creating anything, and a pair naming nothing is refused. Everything else an engine reports is equally forgeable, and everything the reporter relays is something the keeper was told rather than something it checked.

**The reference is a correlation hint, not a credential.** Nothing is granted, billed or gated on it. A wrong one costs a wrong lookup. The day something authorizes off an external reference, this design has to change before that ships.

**External references are not unique.** The keeper does not enforce uniqueness across streams. A step's `engine_reference` is recorded as given and nothing compares it against any other step's, so two steps can name one engine run and neither is refused.

The keeper owns every genesis, so a duplicate reference is a relay mistake on records that already existed rather than a second record of one fact.

**The conductor calls the keeper, and `python -m conductor` is the process that does it.** It asks what has been dispatched to its beamline, claims one execution, walks it, and reports each step as the step ends, all over the same HTTP surface the reporter uses. An engine's own reference reaches a caller of a walk on a finished step and goes no further: it is the reporter that sends one to the keeper, and it is a correlation hint rather than a key.

## When a client does start calling the keeper

The reporter has already settled the four questions any keeper client meets. A second client should answer them the same way rather than differently.

| question | the answer |
| --- | --- |
| how is a repeated send made safe | derive the key from the thing itself, so a restart recomputes it having stored nothing. Registering a dataset is keyed on the step and the store's address together: without the address a run that wrote two datasets records one, and without the step two runs that wrote one address record one |
| which calls need a key at all | only the ones that create. Reporting a run sends none, because that route is idempotent on an opening and lax about the deliveries after it, which a reporter draining a stream depends on |
| what does a 409 mean | usually that the work is already done, not an error. It is an outcome to record, not a failure to raise |
| which refusals are worth retrying | 429 and 5xx. Everything else will fail identically however many times it is sent, and one adapter reads the status so nothing above it has to know statuses are numbers |
| when to raise instead of report | raise means "ask me again", an outcome means "finished with" |

Each answer is a rule rather than a location, because the locations have moved
before and this page did not notice.
