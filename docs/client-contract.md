# Client contract

*How the keeper's peer clients name the same work, and what that name is not.*

This page exists in all three projects, word for word. They share no code
and ship separately, so the agreement is prose in each of them rather than a
package none of them wants to depend on. What holds the copies honest is not
this page: it is that the two metadata keys are pinned to literals in a test
on each side, and renaming one fails the other.

The keeper has two clients that are not part of it. The reporter watches an acquisition engine and records what it sees. The conductor composes a procedure and drives a beamline through it, holding a device claim for each step. Neither imports `keeper`, nothing in the keeper imports either, and they do not import each other.

They nevertheless talk about the same work, so they need one answer to "which acquisition is that". This page is that answer. It is prose rather than a shared package on purpose: a third project existing to hold a string and four HTTP rules would cost more than the duplication it saves.

## One acquisition has two names

An engine mints its own identifier for every run it opens and puts it in the start document it publishes. The keeper's names exist earlier: the execution and the step are written when the procedure is dispatched, before anything is asked of an engine. Metadata passed at the call arrives in the start document unchanged, which a spike measured against a real engine.

So one acquisition carries both:

| | minted by | known at | where it appears |
| --- | --- | --- | --- |
| run uid | the engine | the moment the run opens | `start["uid"]` |
| execution and step ids | the keeper | at dispatch, before the plan is submitted | `start["keeper_execution_id"]`, `start["keeper_step_id"]` |

An earlier draft of this table named a single key holding one reference the driver minted, and no such key exists. Two travel, because a step is an entity inside the Execution aggregate rather than a stream of its own, so naming one means naming the execution around it.

## The keeper reference travels outward, and the engine's uid comes back

This section used to say the opposite, and the inversion is worth recording rather than overwriting.

The old arrangement was that the reporter filed a run into the keeper under the engine's uid, and anything wanting to find that run asked the keeper for the same pair. The keeper held no record of the work before the engine ran it, so the engine's own name was the only thing both sides could agree on.

The keeper now composes the work and dispatches it, so the ids exist before an engine is asked for anything. Whatever drives an execution carries the step's execution id and step id into the engine's own metadata, and the reporter reads them back out: `KEEPER_METADATA_KEYS` in the reporter's `translate` module is where the spelling is written down, and nothing else in either tree knows it.

That means a keeper identifier now sits in somebody else's records, which nothing in this tree had done before. It was weighed rather than assumed. What it buys is that the reporter resolves nothing, carries no plan map, and cannot join the wrong record; what it costs is that a document with no such reference cannot be attributed at all, and is skipped.

The engine's own uid still travels, in the other direction, as a step's `engine_reference`. It is a correlation hint rather than a key: nothing checks that such a run exists, and nothing could, because whatever watches the engine records it on its own schedule.

**Both sides are now implemented.** `conductor.adapters.bluesky_acquisition` writes the pair into the start document of every run it opens under a dispatch, and `reporter.translate` reads it back. The spelling is written out in both projects, which share no code and ship separately, and each pins the two literals in a test that names the other side. A run opened outside a dispatch carries neither key, which is how a scan somebody ran by hand stays distinguishable from work this system is owed a report on.

## Two settings that have to agree

The scheme is a word, and two deployments have to pick the same one.

- The reporter reads `external_ref_scheme` from the `[store]` table of its TOML configuration and sends it with every dataset it registers. A spike recommends a word for the engine it drove, and what a given deployment settled on is written down in its descriptor under `beamlines/`.
- Anything that later resolves a dataset's address must read it under that same word.

Nothing checks this. Two deployments configured differently file data under two vocabularies that look alike and are not, and nothing in the keeper can tell them apart, because the scheme names a vocabulary rather than an instance.

This section used to say the reporter sent the scheme with every run and that a conductor looked runs up by it. Neither is true now: the reporter creates nothing, and there is no lookup from an engine's reference to the step that opened it.

## What this page does not promise

**The metadata is writable by anyone who can start a plan.** The engine is outside the keeper, so the two keys can be set by hand, copied between runs, or left off. What that buys an attacker is narrower than it was: the ids name records the keeper already wrote, so a forged pair moves an existing step rather than creating anything, and a pair naming nothing is refused. `plan_name` and `exit_status` remain equally forgeable, and everything the reporter relays is something the keeper was told rather than something it checked.

**The reference is a correlation hint, not a credential.** Nothing is granted, billed or gated on it. A wrong one costs a wrong lookup. The day something authorizes off an external reference, this design has to change before that ships.

**External references are not unique.** The keeper does not enforce uniqueness across streams. A step's `engine_reference` is recorded as given and nothing compares it against any other step's, so two steps can name one engine run and neither is refused.

That used to be the sharper problem, because an outside reporter opened records and two of them could answer to one reference. It is smaller now: the keeper owns every genesis, so a duplicate reference is a relay mistake on records that already existed rather than a second record of one fact.

**The conductor calls the keeper, and `python -m conductor` is the process that does it.** It asks what has been dispatched to its beamline, claims one execution, walks it, and reports each step as the step ends, all over the same HTTP surface the reporter uses. `Acquired.engine_reference` still reaches a caller through `Done`, and it is still a correlation hint rather than a key.

## When a client does start calling the keeper

The reporter has already settled the four questions any keeper client meets. A second client should answer them the same way rather than differently.

| question | the answer | where the reporter keeps it |
| --- | --- | --- |
| how is a repeated send made safe | derive an idempotency key from the thing itself | `client.idempotency_key_for` |
| what does a 409 mean | usually that the work is already done, not an error | `outcomes.Unchanged` |
| which refusals are worth retrying | 5xx and 429; everything else will fail identically | `session.is_worth_retrying` |
| when to raise instead of report | raise means "ask me again", an outcome means "finished with" | `outcomes` module docstring |
