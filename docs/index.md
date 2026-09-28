---
template: home.html
---

# Reports what happened, and where the data went.

The reporter is how results get back. It reads the stream of messages an
acquisition engine produces during a run, turns each one into a report about the
step it belongs to, and says where the data that step produced is stored. It runs
next to the engine, because that is where the messages are.

**It invents nothing.** Every report names work that was written down before the
engine was ever asked to do it. A message that refers to no such work is skipped
rather than turned into a new record: it is a scan somebody ran by hand, it is
real work, and there is nothing here to attach it to. Skipped quietly, because
complaining about every message of every hand-run scan teaches people to ignore
the channel.

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

## What it will not claim

**That a run was any good.** Everything it files is something it was told, not
something it checked. An engine reporting success is a claim, it travels as one,
and nothing here dresses it up as a finding.

**That nothing was lost.** Messages are held in memory between arriving and being
filed, and a publisher drops what it sends while nobody is listening, so a
message sent while this is down was never sent as far as this is concerned. At
most once, known rather than accidental.

## The pages

**Running one**, if you have to install one beside an engine.

| Page | What it answers |
| --- | --- |
| [Running one](running.md) | The two ways to run one, what must not be pickle, and how to configure it |

**Understanding it**, if you want to know what it does and why.

| Page | What it answers |
| --- | --- |
| [Reporting](reporting.md) | What one reporter does, the two facts an ending carries, and what it will not claim |
| [Architecture](architecture.md) | The split that makes a second engine a translation, and how this is checked without a beamline |
| [Contract](client-contract.md) | The agreements this keeps at its edges: two names for one measurement, and the keys that join them |
| [Glossary](glossary.md) | The words shared with the record, and what each one is pinned to |

**Changing it**, if you are editing the code.

| Page | What it answers |
| --- | --- |
| [Naming](naming.md) | What a name has to do before it is allowed in |
| [Conventions](conventions.md) | What a docstring is for, what a comment has to earn, what a page may claim |
| [Workflow](workflow.md) | Commits, branches, and what a test has to be called |

What this knows about a real engine and a real store is recorded rather than
assumed: two captured files, re-recordable with `make refresh-captures`, and a
suite whose checks are written against the claims they hold. The `README.md` sets
out the design behind that.
