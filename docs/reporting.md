# Reporting

*What a reporter does beside an engine, what it guarantees about what reaches
the record, and what it refuses to claim.*

## The job

An engine produces a stream of messages while it runs. A reporter reads that
stream, turns each message into a report about the step it belongs to, and
files it. When a run ends it also asks where the data that run produced is
kept, and files that too.

```
   an engine  --- messages -->  a reporter  --- reports -->  the record
                                     |
                                     +-- where did this land? --> a store
```

That is the whole job. It reads one engine, files to one record, and asks one
store.

It runs beside the engine rather than inside it. A bug here cannot take a scan
down, the engine never waits on a network, and more than one thing can read the
same stream. Two ways to attach: subscribe to a live engine, or replay a
recording of one. The same path runs behind both, which is how this is tested
without a beamline.

## One run, message by message

A reporter never sees a run whole. It sees messages, in order, and each one
carries only part of what a report needs.

```
   start        the two ids  ------------------------+
   descriptor   which run it belongs to  ---+        |
   reading      which descriptor  ----------+--> run -+--> the step
   stop         which run
```

Only the opening message carries the two ids saying which execution and which
step this run belongs to. A reading does not name its run at all: it names a
descriptor, and only the descriptor message says which run that descriptor
belongs to. So what the opening said has to be held until the run stops.

That includes an opening that said nothing. A run that is not this system's is
remembered as such, because otherwise the pause and the stop of a hand-run scan
would each raise an alert while the start had been quiet. What it holds is what
the stream already delivered, never anything it went and read.

### An ending is two facts

When a run stops, two things became true at once: the engine's run finished,
and the data that run produced exists somewhere. So an ending asks the store
where, and files both.

```
   an engine  --+
                +-->  one reporter  -->  the run finished
   a store    --+                   -->  the data is here
```

One program rather than two, because both are about the same step. A dataset
cites the run that produced it, which is the run the report is about, so the
message that ends a run is the one that knows where to ask.

The store half is optional. No store configured means no lookup and no dataset
filed, and everything else exactly as before. A facility whose engine writes
somewhere the reporter cannot see should record its runs and say nothing about
data.

### Five words for what one delivery came to

```
   Relayed     the record took what the engine said about a step's run
   Kept        a run ended, and where its data went is recorded too
   Unchanged   the record declined it, and is as it was
   Skipped     the delivery carried nothing this system asked for
   Held        something it should have acted on, and could not
```

A message naming no approved work is skipped, and skipped quietly. It is a scan
somebody ran by hand, it is real work, and there is nothing here to attach it
to. An alert on every message of every hand-run scan teaches whoever is
watching to ignore the channel. Nothing is destroyed by it either, so a way of
recording hand-run work could be added later if anybody wants one.

## What it promises

**It invents nothing.** Before an engine is asked to do anything, the job it
belongs to has already been written down and approved, and whatever drives it
carries the two ids into the engine's own metadata. They come back out in the
engine's messages, which is how a reporter knows what a run belongs to. Every
report therefore names something already on the record, and a reporter creates
nothing.

**A redelivered message does not duplicate anything.** Both writes carry a key
worked out from something the reporter can recompute after a restart, having
saved nothing, so a redelivered opening returns the first run's id rather than
recording a second.

The two keys name different things on purpose. One names the run, because an
opening is identified by the run it began. The other names the store's address,
because a dataset is identified by where the data is. They are the same string
today, and they part company the day one run produces two datasets: keyed on
the run, both registrations would carry one note and the second would quietly
come back holding the first one's id.

**The engine's thread never waits on this.** Submitting a report queues it and
returns in microseconds, and a worker thread does the talking. The network this
reporter depends on is not on the path a scan runs down.

**In one process, an ending sees a finished result.** Both callbacks run on the
engine's own thread in the order they were subscribed, so a reporter subscribed
after the writer sees a finished result every time, with no retry and no
waiting. Subscribed before it, the result exists without its ending, the
registration still happens, and the record stamps the arrival time instead.
That guarantee holds in one process only. Over a message bus it really is a
race, and [Running one](running.md) says what a deployment has to get right.

## What it refuses to claim

**That a run was any good.** Everything filed is something the reporter was
told, never something it checked. An engine reporting success is a claim, it
travels as one, and nothing here dresses it up as a finding. What a run meant
is for something further out to decide.

**That it understood anything.** No message is opened to see what it means, no
number is read, and no result is judged. The reporter is a relay, and reading
the stream through the engine's own library would drag the engine in as a
dependency of the thing whose whole claim is that it is not the engine.

**That nothing was lost.** Messages live in memory between arriving and being
filed, and a publisher drops what it sends while nobody is listening. So a
message sent while the reporter is down was never sent as far as the reporter
is concerned. At most once, known rather than accidental.

**That a scan already running when it starts can be filed.** The gap is not
only the messages it missed:

```
   a scan it saw from the start
   [ start ][ reading ][ reading ][ stop ]    every one filed

   a scan already under way when it came up
   [   ?   ][ reading ][ reading ][ stop ]    nothing to attach them to,
       ^                                      and it says so loudly
       never seen
```

The opening carried the two ids and the opening is what was missed, so the rest
of that scan cannot be filed at all. There is no way to ask the record which
step an engine's run belongs to, and closing this needs a question the record
does not answer yet.

**That the tally is the record.** When a report lands and the dataset cannot be
filed, the single outcome for that message has to be the failing one, so a run
against a store that is down reports no successes at all even though every
report landed. The reports are on the record either way. It is the tally that
misleads, not the record.

## Where it stops

A reporter reads and relays. Four things on the other side of that line belong
to somebody else:

```
   running the routine           an engine
   keeping the data              a store
   saying what may run at all    the record
   judging whether it worked     whatever reads the record afterwards
```

It drives nothing and decides nothing, and it holds a reference to each of
those rather than the thing itself.

[Architecture](architecture.md) has the split that makes a second engine a
translation rather than a rewrite, and the two recordings this is checked
against. [Contract](client-contract.md) covers what a client may rely on at
these edges. [Glossary](glossary.md) pins each word shared with the record.
