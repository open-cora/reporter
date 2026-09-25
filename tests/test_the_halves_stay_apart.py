"""The one structural rule this package has, and a check that it holds.

A second engine was driven in a spike and the reporter came out of it
split in two. `translate` and `sources` read one engine and know nothing
about the keeper. `client`, `config`, `session` and `relay` talk to the keeper and
know nothing about any engine. `intents` is the vocabulary between them,
and `wire` is the one place they are joined.

That split is what makes a second engine a translator rather than a
rewrite, and nothing about it is visible in a diff. It was already broken
once, quietly: `client` imported a helper from `translate` because the
helper had been filed on the wrong side, and the module that talks to
The keeper therefore imported the module that reads one engine's documents. No
test failed, because there was no test.

This is that test. It reads imports rather than running anything, which
is why it is cheap enough to keep.

## Why the counts are pinned

Every check below ranges over a set of modules discovered from disk. A
rename, a move, or a typo in a set below silently shrinks that set, and a
rule ranging over nothing passes. The pins are what turn "found nothing to
check" into a failure. Raise one only after confirming the rule now sees
the thing you added, never to make a red run green.
"""

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "reporter"

ENGINE_SIDE = frozenset({"translate", "sources"})
"""Modules that read one engine, and would be replaced for a second one."""

KEEPER_SIDE = frozenset({"client", "config", "session", "relay"})
"""Modules that talk to the keeper, and would be reused for a second engine."""

STORE_SIDE = frozenset({"stores"})
"""Modules that read a store, and would be replaced for a different one.

A third outside system, and neither set above fits it: it does not read an
engine and it does not talk to the keeper.

The keeper side is allowed to name it, which looks like the rule below being
bent and is not. The two outward halves differ in direction. An engine
pushes, so its translator is called from `wire`, above the session, and
the session never names it. A store is asked, so its lookup is called from
inside the session, below it. What the session names is `StoreLookup`, a
Protocol, so a second store is an implementation swapped at the entrypoint
and nothing in here changes. There is no such Protocol on the engine side
because there is nothing to call: documents arrive.
"""

CONTRACT = frozenset({"intents", "outcomes"})
"""The vocabulary both sides share, which is what makes the split possible.

`outcomes` is here rather than on the keeper side because it says what a
caller should do, not what the keeper answered, and a second engine's reporter
reports the same five things.
"""

JOINS_THEM = frozenset({"wire", "__main__", "__init__"})
"""Modules allowed to name both sides.

`wire` because composing them is its whole job, and the other two because
an entrypoint and a package surface reach everything by definition.
"""

STORE_LIBRARIES = frozenset({"tiled"})
"""Store clients no module here may import, for a different reason.

The engine ban below is about identity: this package's claim is that it is
not the engine. This one is about a measurement. The spike read one node
both through the store's client and off its raw HTTP surface and got the
same address four times out of four, so the client would buy insulation
from an envelope that two fields are read out of, and cost a dependency.
A spike is the evidence.

Separate from the set below rather than merged into it, because the two
bans would be lifted for different reasons and a merged set would hide
which argument had stopped holding.
"""

ENGINE_LIBRARIES = frozenset({"bluesky", "ophyd", "databroker", "epics", "caproto", "tomoscan"})
"""Libraries no module here may import.

The wire formats this reads are small and are decoded by hand precisely
so that a package whose claim is that it is not the engine does not
depend on the engine. `apps/keeper` bans these names in prose; this bans
them as imports, which is the failure that would actually matter.
"""

ENGINE_WORDS = frozenset({"document", "descriptor", "datum", "runstart", "runstop"})
"""Engine vocabulary that may not appear in a name off the engine side.

The import rules above keep the two halves from reaching each other. This
keeps the engine's words from drifting across while the imports stay
clean, which is how the leak actually happened: `relay` queued a thing it
never opens and called it a `document`, so the module that knows least
about the engine used its vocabulary in a signature.

**Identifiers only, never prose.** Three passages have to say "document"
to make their point, and all three are explaining this very boundary:
`session` on why `act` takes an `Intent`, `intents` on why `origin` is a
plain string, and `relay` on why the word here is `delivery`. A prose ban
would need a line-level allow-list for them, which is brittle and would
be edited to silence a failure. A name is a flat fact, so the rule is
flat.

`wire` and the two entrypoints are exempt for the reason they are exempt
above: `documents_into` names the engine on purpose, and a second engine
gets a sibling beside it rather than a rename.
"""

EXPECTED_MODULE_COUNT = 12
"""Modules under `src/reporter`, counting `__init__` and `__main__`.

Pinned so that a check ranging over an empty set fails instead of passing.
"""


def modules() -> dict[str, ast.Module]:
    """Every module in the package, parsed."""
    return {
        path.stem: ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for path in sorted(PACKAGE.glob("*.py"))
    }


def imports_of(tree: ast.Module) -> set[str]:
    """Sibling modules this one imports, by bare name."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            parts = node.module.split(".")
            if parts[0] == "reporter" and len(parts) > 1:
                found.add(parts[1])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if parts[0] == "reporter" and len(parts) > 1:
                    found.add(parts[1])
    return found


def outside_imports(tree: ast.Module) -> set[str]:
    """Top-level package names this module imports from outside itself."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
        elif isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
    return found


def identifiers_of(tree: ast.Module) -> set[str]:
    """Every name this module declares, lowercased.

    Definitions, arguments, and anything assigned. Not names it merely
    reads, which would drag in whatever it imported and make the rule
    about other modules' choices.
    """
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            found.add(node.name)
        elif isinstance(node, ast.arg):
            found.add(node.arg)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            found.add(node.id)
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
            found.add(node.attr)
    return {name.lower() for name in found}


def test_the_scan_finds_every_module_it_should() -> None:
    """Guard the scan. Everything below ranges over this."""
    found = modules()

    assert len(found) == EXPECTED_MODULE_COUNT, (
        f"Expected {EXPECTED_MODULE_COUNT} modules under {PACKAGE}, found {sorted(found)}. "
        "Raise the pin in the same commit, once you have confirmed the rules below see it."
    )


def test_every_module_is_placed_on_one_side_or_named_as_joining_them() -> None:
    """A module nobody classified is a module no rule below constrains."""
    classified = ENGINE_SIDE | KEEPER_SIDE | STORE_SIDE | CONTRACT | JOINS_THEM

    assert set(modules()) == classified, (
        "A module is missing from the sets in this file, so no rule below applies to it: "
        f"{sorted(set(modules()) ^ classified)}"
    )


@pytest.mark.parametrize("name", sorted(KEEPER_SIDE))
def test_a_module_that_talks_to_the_keeper_names_no_engine_module(name: str) -> None:
    """The rule that was already broken once.

    An import here is how a second engine stops being a translator and
    starts being a fork.
    """
    reached = imports_of(modules()[name]) & ENGINE_SIDE

    assert not reached, (
        f"`{name}` talks to the keeper and imports {sorted(reached)}, which reads one engine. "
        "Whatever it needs is either misfiled or belongs in `intents`."
    )


@pytest.mark.parametrize("name", sorted(ENGINE_SIDE))
def test_a_module_that_reads_an_engine_names_nothing_but_the_contract(name: str) -> None:
    """The mirror, and the one that keeps a translator portable."""
    reached = imports_of(modules()[name]) - CONTRACT

    assert not reached, (
        f"`{name}` reads one engine and imports {sorted(reached)}. It may name only "
        f"{sorted(CONTRACT)}, or a second engine's translator inherits this too."
    )


@pytest.mark.parametrize("name", sorted(STORE_SIDE))
def test_a_module_that_reads_a_store_names_nothing_but_the_contract(name: str) -> None:
    """The same rule the engine side gets, for the same reason.

    A lookup that reached into `session` or `client` would make a second
    store a change to this reporter rather than a class implementing a
    Protocol.
    """
    reached = imports_of(modules()[name]) - CONTRACT

    assert not reached, (
        f"`{name}` reads a store and imports {sorted(reached)}. It may name only "
        f"{sorted(CONTRACT)}, or a second store stops being an adapter swap."
    )


@pytest.mark.parametrize("name", sorted(KEEPER_SIDE | CONTRACT | STORE_SIDE))
def test_a_module_off_the_engine_side_keeps_engine_words_out_of_its_names(name: str) -> None:
    """The vocabulary half of the split, which the import half missed.

    `relay` held `document` in two signatures while importing nothing
    from the engine side, so every rule above passed.
    """
    reached = {
        identifier
        for identifier in identifiers_of(modules()[name])
        for word in ENGINE_WORDS
        if word in identifier
    }

    assert not reached, (
        f"`{name}` is off the engine side and declares {sorted(reached)}. "
        "What arrives is a `delivery` and its opaque half is a `payload`; a "
        "second engine sends neither documents nor descriptors."
    )


@pytest.mark.parametrize("name", sorted(ENGINE_SIDE))
def test_a_module_that_reads_an_engine_never_names_a_store(name: str) -> None:
    """The two outward halves have nothing to say to each other.

    A translator that read a store would be answering "where did the data
    go" from inside "what did the engine say". Joining those two is the
    session's job, because only the session holds the id they join on.
    """
    reached = imports_of(modules()[name]) & STORE_SIDE

    assert not reached, f"`{name}` reads an engine and imports {sorted(reached)}, which is a store."


@pytest.mark.parametrize("name", sorted(CONTRACT))
def test_the_contract_depends_on_neither_side(name: str) -> None:
    """A vocabulary that imported one side would not be shared, it would
    belong to that side."""
    reached = imports_of(modules()[name]) & (ENGINE_SIDE | KEEPER_SIDE | STORE_SIDE)

    assert not reached, f"`{name}` is the shared vocabulary and imports {sorted(reached)}."


def test_only_one_module_joins_the_two_sides() -> None:
    """`wire` is findable because it is the only one, and the split is
    only as good as that being true."""
    joiners = {
        name
        for name, tree in modules().items()
        if name not in {"__init__", "__main__"}
        and imports_of(tree) & ENGINE_SIDE
        and imports_of(tree) & KEEPER_SIDE
    }

    assert joiners == {"wire"}, f"Expected only `wire` to name both sides, found {sorted(joiners)}."


@pytest.mark.parametrize("name", sorted(set(modules())))
def test_no_module_imports_an_engine_library(name: str) -> None:
    """The dependency this package refuses, and the reason `sources`
    decodes a published frame by hand."""
    reached = outside_imports(modules()[name]) & ENGINE_LIBRARIES

    assert not reached, f"`{name}` imports {sorted(reached)}, which is an engine."


@pytest.mark.parametrize("name", sorted(set(modules())))
def test_no_module_imports_a_store_library(name: str) -> None:
    """The dependency the spike measured as unnecessary rather than refused."""
    reached = outside_imports(modules()[name]) & STORE_LIBRARIES

    assert not reached, f"`{name}` imports {sorted(reached)}, which is a store client."


@pytest.mark.parametrize("name", sorted(set(modules())))
def test_no_module_imports_the_keeper_itself(name: str) -> None:
    """Separate deployables, and the separation is the interpreter's rule
    rather than a convention only while this passes."""
    assert "keeper" not in outside_imports(modules()[name]), (
        f"`{name}` imports `keeper`. This is a client of that API over HTTP, and a "
        "reporter that can reach the model directly is not a separate deployable."
    )


def test_the_engine_word_ban_would_catch_something() -> None:
    """A name check that matched nothing would pass on a clean tree and on
    a tree full of leaks alike.

    The first case is the leak this rule was written for, in the shape it
    actually had. The last is the reason the check is on declarations
    rather than on every name: a module may still read one.
    """
    pretend = ast.parse(
        "def submit(self, document):\n"
        "    self._descriptor = document\n"
        "\n"
        "def handle(self, payload):\n"
        "    return other.document\n"
    )

    declared = identifiers_of(pretend)

    assert {word for word in ENGINE_WORDS if word in " ".join(declared)} == {
        "document",
        "descriptor",
    }
    assert "payload" in declared
    assert "other" not in declared


def test_the_engine_library_ban_would_catch_something() -> None:
    """A banned-name check that matched nothing would pass on an empty
    list as readily as on a clean tree."""
    pretend = ast.parse(
        "import bluesky\nimport tiled.client\nfrom keeper.execution import Execution\n"
    )

    assert outside_imports(pretend) & ENGINE_LIBRARIES == {"bluesky"}
    assert outside_imports(pretend) & STORE_LIBRARIES == {"tiled"}
    assert "keeper" in outside_imports(pretend)
