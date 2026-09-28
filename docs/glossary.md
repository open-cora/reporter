# Glossary

*The words this project shares with the keeper, and what each one is pinned to.*

Every term here is the keeper's, copied rather than linked, because the two
projects ship separately and a shared word that drifted would be worse than a
word written twice. The keeper's own glossary is the longer one: it also holds
the vocabulary of bounded contexts, events and projections, none of which this
project has.

A term used here and not listed is either plain English or this project's own,
and this project's own are defined where they are declared.

## The work

- **Operation.** A runnable routine this system holds a record of: the name the engine knows it by, and the JSON Schema a run of it must satisfy. Defined, not registered: nothing anywhere pairs that name with that schema until the record says so.
- **Routine.** The thing out in the engine that an operation's name points at. Not modelled here, and named with a plain word rather than a term, because this system holds a reference to it and never the thing itself.
- **Procedure.** A routine this system composed, written down: an ordered list of steps, each naming what it touches. The contrast with an **operation** is who authored the routine. An operation names something an engine already has and a procedure names something nothing knows until this system says so, which is why an operation's name is a handle in someone else's vocabulary and a procedure's steps are not.
- **Step.** One element of a procedure. Two kinds: a **set**, which sends one record to one value, and a **run**, which hands an operation to whatever performs it. The contrast is where the work is determined: a set is fully specified by the step, and a run is a name in someone else's vocabulary. Only a run declares the devices it touches, because only a set's are derivable from the step itself.
- **Scope.** One piece of a device namespace, named as a string and claimed whole. Stored here as written and parsed nowhere: the grammar belongs to whatever drives the procedure, and the arithmetic over collisions runs in that process.
- **Execution.** One traversal of a procedure: the record this system opens when it dispatches one, and how far the thing driving it got. Every step of it is either reported by a driver or left unreported, and the record says which.
- **Execution status.** How far an execution has got: Dispatched, Claimed, Running or Ended. Derived in the fold from which events the stream carries, never stored. Dispatched is the one transient state in this tree: the record exists and nothing has taken it up, which is a state that only becomes possible once this system hands work out.
- **Engine state.** What an engine was reported to have done to the run one step opened: Running, Paused, Completed, Aborted or Failed. The second of two observers of one step, beside the driver's outcome, and the two are allowed to disagree because neither is reliable and collapsing them would make this system pick a winner between two claims it cannot check.
- **Run.** One step that hands an operation out to be performed, and the carrying-out it causes. One word for both, because they are one fact: the step this system composed and the thing an engine did about it. Chosen over **run**, which names collecting data, when what the step actually does is delegate. A run may collect nothing, and the ones that transfer or compute will collect nothing at all. What an engine did with it is on the step, as an `engine_reference` and an engine state.
- **External reference.** An open-scheme `(scheme, value)` pair naming something in a system outside this one. The scheme names the issuing authority and the value is opaque to it. A dataset carries one, because data this system cannot point back at cannot be found.
- **Reported.** Of a step or of an engine's account of one: performed somewhere else, and made known to this system by someone or something telling it afterwards. The contrast pair is **composed**, of the work this system authored itself. It claims only what this system can back: that it was told. "Witnessed" would fail that, because to witness is to have been present and able to vouch, and this system was neither.
- **Engine.** Whatever actually runs a routine, outside this system. Named by role rather than by product, because which one a deployment runs is a deployment's fact.

## The data

- **Dataset.** One body of data a run produced, as this system came to know about it: which step made it, and what the store holding it calls it. Not the data, and not a description of it. The word is the one people say out loud for this thing, and it is defined here rather than avoided because the store's own vocabulary uses it for something narrower; nothing in this system imports that vocabulary.
- **Store.** Whatever actually keeps the data a run produced, outside this system. Named by role rather than by product, for the same reason **engine** is: which one a deployment runs is a deployment's fact. The contrast with an engine is what each one is asked for, not how either is reached.
