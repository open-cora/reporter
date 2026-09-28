# Naming

*What a name has to do before it is allowed into this project.*

The chassis rules, and only the parts that bind a plain Python library. The
keeper carries the rest, because they are about bounded contexts, event
sourcing and a database this project does not have.

The keeper carries four more rules than these, about events, commands and
error classes. They are real rules and they are about things this project does
not have.

## R1: Read-aloud test

Say the name out loud. If it does not read like natural English, it is a smell, even when it parses correctly as code.

- "default parameters" reads naturally.
- "parameter defaults" stalls. It works as an adjectival construction, but not as a domain noun.

The trap is that code identifiers compose without grammar checks. `parameter_defaults: dict` typechecks fine. The compiler does not notice that English speakers will say "the default parameters". Identifiers that fight English become identifiers people misremember, mistype, and have to look up.

**Also count the term's domain overloads.** A term that reads naturally in isolation can have hidden collisions. At lock time, list the distinct meanings the word already carries in this domain. If there are more than three, look harder.

## R2: Symmetry across the family

When a related family of names exists (defaults / overrides / effective; declared / derived / cached), every member must share the same word-order skeleton.

Ask: if I list every member of this family, do they all share a skeleton? If not, fix it before locking.

**A family has a MEANING, not just a size.** Before adopting a family on a member-count argument, read two or three of its members and check that the family holds a meaning the new member shares. `to_X` returning something that is not an `X` joins the big family while breaking its semantics, which is worse than the outlier it replaced. Every cited fact can be true and the conclusion still wrong.

## R3: Family-noun primacy, with the role as an adjective prefix

**The family noun goes LAST. The role goes first, as an adjective.**

```
<role>_<family-noun-plural>

default_parameters     override_parameters     effective_parameters
default_settings       override_settings       effective_settings
```

This matches how English assembles compound nouns. The family noun carries the primary meaning; the adjective specializes it.

The counter-example to avoid is `<family>_<role>`, which puts the abstract family noun first and a role noun second, pretending to be a suffix. It is grammatical but awkward in use.

**This rule is read backwards more often than any other in this document.** R3 says noun-LAST. Before proposing a rename on R3 grounds, re-read this section.

The schema is the exception: a schema describes the family rather than specializing within it, so `parameters_schema` is family-noun plus descriptor. There is no role, because a schema is not a role within the family. It IS the family contract.

**Collective nouns are not plurals.** "Wiring" and "plumbing" read naturally in speech but break the field-name pattern. Use the plural for a collection field and reserve the collective for a higher-level concept label.

## R4: Lock-time read-aloud process

Before locking a design, run the R1 and R2 checks once more over every name in it. This is mechanical, takes about five minutes, and catches what mid-design momentum hides.

1. List every new name introduced: fields, classes, functions, error classes.
2. For each, say it aloud. Awkward? Flag it.
3. Group into families by shared role-words. Do the skeletons match? If not, flag.
4. Fix anything flagged and re-list.
5. Then lock.

## Where these rules do not apply

- **Single-instance fields** with no family. R2 has nothing to check. R1 still applies.
- **Industry-standard names** that follow a different convention. `created_at` and `occurred_at` are standard; do not rename them for symmetry with anything.
- **Names that landed before a rule existed.** Apply the rules to new work and let old work pass through normal evolution, unless a rename is independently motivated.
