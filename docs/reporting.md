# Reporting

What one reporter does, what it promises, and what it refuses to claim.

## What it does

An engine produces a stream of messages while it runs. A reporter
reads that stream, turns each message into a report about the step it belongs
to, and files it. When a run ends it also says where the data that run produced
is stored.

```
   engine  ---->  messages  ---->  reporter  ---->  the record
                                       |
   store  <------- where did  --------+
                   this land
```

That is the whole job. It reads one engine, files to one record, and asks one
store where things went.

## It reports work that already existed

Before an engine is asked to do anything, the job it belongs to has already been
written down and approved, and whatever drives it carries two ids into the
engine's own metadata: which execution, and which step. Those ids come back out
in the engine's messages, which is how a reporter knows what a run belongs to.

So every report names something already on the record. A reporter creates
nothing and invents nothing.

**A message with no such ids is skipped.** It is a scan somebody ran by hand,
it is real work, and there is nothing here to attach it to. Skipped quietly
rather than loudly, because an alert on every message of every hand-run scan
teaches whoever is watching to ignore the channel. Nothing is destroyed, and a
way of recording hand-run work could be added later if anybody wants one.

## One ending, two facts

When a run stops, two things became true: the engine's run finished, and the
data that run produced exists somewhere. So an ending asks the store where, and
files both.

```
   engine  --+
             +-->  one reporter  -->  the run finished
   store   --+                   -->  the data is here
```

One process rather than two, because both are about the same step. A dataset
cites the run that produced it, which is the run the report is
about, so the message that ends a run is the one that knows where to ask.

**The store half is optional.** No store configured means no lookup and no
dataset filed, and everything else exactly as before. That is a deployment
rather than a broken one: a facility whose engine writes somewhere the reporter
cannot see should record its runs and say nothing about data.

**Subscribe the writer first.** Both callbacks run on the engine's own thread in
the order they were subscribed, so a reporter subscribed after the writer sees a
finished result every time, with no retry and no waiting. Subscribed before it,
the result exists without its ending, the registration still happens, and the
record stamps the arrival time instead. That guarantee holds in one process
only; over a message bus it really is a race.

## Why it remembers things

Two maps, and the second matters more.

A reading message does not name its run. It names a descriptor, and only the
descriptor message says which run that descriptor belongs to. Meanwhile only the
opening message carries the two ids that say which step this is.

```
   start        the two ids  ------------------------+
   descriptor   which run it belongs to  ---+        |
   reading      which descriptor  ----------+--> run -+--> the step
   stop         which run
```

So what the opening message said has to be held until the run stops. That
includes an opening that said nothing: a run that is not this system's is
remembered as such, because otherwise the pause and the stop of a hand-run scan
would each raise an alert while the start had been quiet.

It is still a pure piece of code. What it holds is what the stream already
delivered, not anything it went and read.

**Restarting mid-scan loses the runs in flight.** There is no way to ask the
record which step an engine's run belongs to, so the remaining messages of that
scan cannot be filed and say so loudly. Closing one needs a question the record
does not answer yet.

## What it will not claim

**That a run was any good.** Everything filed is something the reporter was
told, never something it checked. An engine reporting success is a claim, it
travels as one, and nothing here dresses it up as a finding. What a run meant is
for something further out to decide.

**That it understood anything.** No message is opened to see what it means, no
number is read, and no result is judged. The reporter is a relay.

**That nothing was lost.** Messages live in memory between arriving and being
filed, and a publisher drops what it sends while nobody is listening. So a
message sent while the reporter is down was never sent as far as the reporter is
concerned. At most once, known rather than accidental.

**That a summary is the record.** When a report lands and the dataset cannot be
filed, the single outcome for that message has to be the failing one, so a run
against a store that is down reports no successes at all even though every
report landed. The reports are on the record either way. It is the tally that
misleads, not the record.

## Redelivery is safe

Both writes carry a key worked out from something the reporter can recompute
after a restart, having saved nothing. A redelivered opening returns the first
run's id rather than recording a second run.

The two keys name different things on purpose. One names the run, because an
opening is identified by the run it began. The other names the store's address,
because a dataset is identified by where the data is. They are the same string
today and they part company the day one run produces two datasets: keyed on the
run, both registrations would carry one note and the second would quietly come
back holding the first one's id.
