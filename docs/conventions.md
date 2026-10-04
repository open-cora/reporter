# Conventions

*What a docstring is for, what a comment has to earn, and what a page may
claim.*

The chassis rules, and only the parts that bind a plain Python library. The
keeper carries the rest, because they are about bounded contexts, event
sourcing and a database this project does not have.

Naming is in [Naming](naming.md); commits and test names are in
[Workflow](workflow.md). This page is what is left, and it is all about writing
things down.

## Documentation

Docstrings carry intent. Comments carry hidden constraints. Test names carry scenarios. Everything else is noise.

### Which home a claim belongs in

There are two places a rule can be written down, and writing it in both is how
they drift. The split:

| | Owns | Example |
| --- | --- | --- |
| `docs/` | The RULE. What the convention is, why it exists in general, what the anti-patterns are. | "A port is a Protocol, and its adapters are named for the technology behind them." |
| A docstring | The SITE. Why THIS module implements the rule the way it does, and what is non-obvious here. | "This store is one instance per process, because more than one BC appends through it." |

A docstring that restates the general rule is duplication. Link instead: open by
naming the convention page, then explain only what this seam adds.

**A fact may appear in both; a rationale may not.** The key that makes a
redelivered registration harmless is stated in [Contract](client-contract.md)
and again on the seam, because a reader of the seam must see the contract
without leaving the file. What must NOT appear twice is the reason for it: two
explanations of one decision become two decisions the first time someone edits
one.

When they do conflict, the page wins and the docstring is the bug.
It is the page a reader consults before writing code, so a stale rule there
misleads earlier and wider than a stale docstring does.

### Do not describe machinery that does not exist

Write a rule as a rule. Do not write it as a description of enforcement unless
the enforcement is there: "enforced by `test_x.py`" is a claim a reader will
check by reading the sentence, not the directory.

Every project here began as a copy of a chassis, and the claims came with the
copy: rules saying they were enforced by a test that lives in the repository the
chassis came from and not in this one. Each project had to go through its own and
either delete the claim or make it true. A rule known to be unenforced is still
useful. A rule wrongly believed to be enforced is worse than no rule, because
nobody looks twice at it.

The same applies to evidence. A measurement belongs to the system that
measured it; quoting a sibling project's numbers to justify a decision here
makes the reasoning unfalsifiable, since nothing in this tree can reproduce
or refute them.

No emoji anywhere in source: comments, docstrings, log strings, error messages, `Field(description=...)`. Emoji in source is a documented LLM tell that accumulates as noise across reviews. This mirrors the no-em-dash rule applied to prose.

### Citing an external source

Two different things get called a citation, and they need different links.

**Reading a source: link the moving ref.** A navigational link wants whatever that page says today, so link `main`, `HEAD`, or `/en/latest/`. Pinning a navigational link sends the reader to a stale copy, which is worse than no link.

**Sourcing a value: identify the version.** When a number, an address, a serial, or a step order is recorded because an external artifact said so, the citation has to say which state of that artifact. Otherwise the value silently stops matching its own source the next time the source changes, and nothing here notices. Use a commit SHA for a repository, and for a page with no addressable version, keep the readable link and name the date the value was folded from it beside the value.

The distinction is not about how important the source is. It is about whether this project is repeating a claim. A record whose provenance means "whatever that file says now" is not a record.

Verify before pinning: read the source at the ref you are about to cite. A wrong pin is more misleading than a moving one, because it looks checked.

### Docstrings

Every public module, class, function, and method gets a docstring. Style is prose, not Sphinx.

- **One imperative summary line.** Single-line docstrings stay on one line and end with a period. Carve-out: a port `Protocol` class describes a seam, not an action, so its summary may lead with a role noun-phrase.
- **Prose body when more is needed.** Blank line after the summary, then narrative paragraphs. Use Markdown subheaders (`## Section`) for distinct concerns.
- **Domain vocabulary matches the [glossary](glossary.md).** A seam is a seam, not an interface. An adapter is an adapter, not a driver.
- **Cross-references**: backticks for in-module symbols; a dotted path for anything in another module.

#### A docstring may not name code or files that do not exist

Backticks mean "this is a symbol". A reader who cannot find a backticked
name has no way to tell a name they have missed from a name that is not
there, so every dangling reference costs a search that ends in nothing.

Two fitness tests in `test_docstring_references_resolve.py` enforce this. A
backticked name whose shape says it is code, meaning CamelCase, a
screaming-snake constant, a leading-underscore private name or a snake_case
name, must be bound somewhere in `src` or `tests`. A cited file path must
exist in this project.

The scan is scoped to this project rather than to whatever tree surrounds
it, and that is the half that earns its keep. A citation of a neighbouring
directory resolves for exactly as long as the neighbour is next door.

The tests admit three declared exceptions, each a named frozenset:

| | For | Example |
|---|---|---|
| `EXTERNAL_NAMES` | Real, defined outside this project | `EngineReport`, which the keeper defines |
| `PROSPECTIVE_NAMES` | Real nowhere, deliberately | `test_handler_works`, a stand-in inside a worked example |
| `EXTERNAL_FILES` | A real file this project does not hold | `reporter.toml`, which an operator writes |

`PROSPECTIVE_NAMES` exists because naming a thing before it exists, or
after it stops existing, is a legitimate move: telling a future author what
to call something, standing in for a type inside a worked example, or
saying what a removal removed. Each entry still costs a line, so adding one
is a decision rather than a way past the check.

Neither test can see a wrong explanation of a real symbol. They catch the
cheaper failure, which is prose that refers to nothing at all. The first run over this
project found five of them, and two citations of a file an operator
writes.

Use a word instead of a symbol when you mean a word: an `Adapter` suffix is
a string, not a class, and the backticks claim otherwise.

**Anti-patterns:**

- Do not use `Args:` / `Returns:` / `Raises:` sections. Type annotations are the parameter contract; raised exceptions belong in prose when non-obvious.
- Do not restate the type signature in prose.
- Do not write `>>>` doctest examples. The tests are external.
- Do not name a phase, iteration, or audit in a docstring. Those rot. The current code is what is true; ordering lives in git history. Name the precedent itself, not the phase that shipped it.

### Comments

Default to none. Well-named identifiers carry WHAT.

Add a `#` comment only when the WHY is non-obvious: a hidden constraint, a subtle invariant, a workaround for a specific bug, behavior that would surprise a reader. State the constraint, not the history.

**Anti-patterns:**

- Do not narrate WHAT the next line does. The code says that.
- Do not annotate the current task, fix, or caller. Git log and the PR description are the right home.
- Do not leave dead-code markers (`# was`, `# previously`, `# old`). Delete the dead code.
- Do not leave `# TODO`, `# FIXME`, `# HACK` without an owner and a trigger. File an issue or drop it.
- Do not use `# noqa: <code>` without a trailing comment explaining the suppression.
- Do not draw section dividers. One concern per module already provides navigation.

### Tests

Test names carry scenarios. Per-test docstrings stay rare.

- **`test_<subject>_<scenario>_<expectation>`** is the naming convention. Long is fine.
- **Property-based tests document the property**, not the test shape. The `@given` body is the test; the docstring is the invariant being verified.
- **Architecture tests document the rule, the rationale, and the exception.** They are the structural guardrails; a future contributor needs to know why each rule exists.
- **Fixture docstrings only when non-obvious.** A soft IOC, a faked transport, and similar subtleties get one paragraph in `conftest.py`. Simple fixtures stay bare.
