---
template: home.html
---

# Reports what happened, and where the data went.

The reporter is how results get back. It reads the stream of messages an engine produces during a run, turns each one into a report about the step it belongs to, and says where the data that step produced is stored. It runs next to the engine, because that is where the messages are.

## Where this sits

Beamline software assumes somebody is watching. CORA is four programs for the case where nobody is, carrying the three things a person supplied by being present: the judgement about what to run next, the authority that made it permitted, and the account of what was actually done.

| | |
| --- | --- |
| [Keeper](https://github.com/open-cora/keeper) | holds the record, and who may add to it |
| [Conductor](https://github.com/open-cora/conductor) | runs the work at the beamline |
| **Reporter** | reports what happened, and where the data went |
| [Thinker](https://github.com/open-cora/thinker) | suggests what to run next |

**This is how what happened gets back**, from the engine to the record, while nobody is watching either. [CORA](https://github.com/open-cora/cora) sets out why the four exist and how they fit.

## What it enables

**Results reach whatever decides next, with nobody in the loop.** While somebody is watching a run, getting results back is a convenience. The moment work runs unattended it is the only thing making what happened visible to whatever decides what happens next, and it has to keep working while nobody is watching it either.

**A second engine costs a translation, not a rewrite.** The half that reads an engine and the half that files a report do not know about each other, so a new engine costs only the vocabulary it speaks.

**Hand-run scans keep working beside it.** A message naming no approved work is skipped rather than turned into a new record, so a beamline adopting this does not have to stop doing things the old way first.

## How

It sits next to the engine rather than inside it. A bug here cannot take a scan down, the engine never waits on the network, and more than one thing can read the same stream.

**It invents nothing.** Every report names work that was written down before the engine was ever asked to do it. A message that refers to no such work is skipped quietly, because complaining about every message of every hand-run scan teaches people to ignore the channel.

**It reads none of it.** No message is opened to see what it means, no number is checked, and nothing is judged. What arrives is passed on word for word, and something further out decides what it was.

## What it will not claim

**That a run was any good.** Everything it files is something it was told, not something it checked. An engine reporting success is a claim, it travels as one, and nothing here dresses it up as a finding.

**That nothing was lost.** Messages are held in memory between arriving and being filed, and a publisher drops what it sends while nobody is listening, so a message sent while this is down was never sent as far as this is concerned. At most once, known rather than accidental.

## Where it stands today

Subscribe mode has read a real engine's stream and filed reports from it. It also replays a recording, which is how it is tested without a beamline. What is still missing is durability: there is nothing behind the transport to ask again, so the at-most-once above is a cost rather than a bug.

## The pages

| Page | What it answers |
| --- | --- |
| [Running one](running.md) | The two ways to run one, what must not be pickle, and how to configure it |
| [Reporting](reporting.md) | What one reporter does, the two facts an ending carries, and what it will not claim |
| [Architecture](architecture.md) | The split that makes a second engine a translation, and how this is checked without a beamline |
| [Contract](client-contract.md) | The agreements this keeps at its edges: two names for one measurement, and the keys that join them |
| [Glossary](glossary.md) | The words shared with the record, and what each one is pinned to |
| [Naming](naming.md), [Conventions](conventions.md), [Workflow](workflow.md) | The rules to keep when editing this code |

What this knows about a real engine and a real store is recorded rather than assumed: two captured files, re-recordable with `make refresh-captures`, and a suite whose checks are written against the claims they hold. The `README.md` sets out the design behind that.
