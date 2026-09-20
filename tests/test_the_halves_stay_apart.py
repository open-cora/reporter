"""The one structural rule this package has, and a check that it holds.

A second engine was driven in a spike and the reporter came out of it
split in two. `translate` and `sources` read one engine and know nothing
about AROC. `client`, `config`, `session` and `relay` talk to AROC and
know nothing about any engine. `intents` is the vocabulary between them,
and `wire` is the one place they are joined.

That split is what makes a second engine a translator rather than a
rewrite, and nothing about it is visible in a diff. It was already broken
once, quietly: `client` imported a helper from `translate` because the
helper had been filed on the wrong side, and the module that talks to
AROC therefore imported the module that reads one engine's documents. No
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

AROC_SIDE = frozenset({"client", "config", "session", "relay"})
"""Modules that talk to AROC, and would be reused for a second engine."""

CONTRACT = frozenset({"intents", "outcomes"})
"""The vocabulary both sides share, which is what makes the split possible.

`outcomes` is here rather than on the AROC side because it says what a
caller should do, not what AROC answered, and a second engine's reporter
reports the same five things.
"""

JOINS_THEM = frozenset({"wire", "__main__", "__init__"})
"""Modules allowed to name both sides.

`wire` because composing them is its whole job, and the other two because
an entrypoint and a package surface reach everything by definition.
"""

ENGINE_LIBRARIES = frozenset({"bluesky", "ophyd", "databroker", "epics", "caproto", "tomoscan"})
"""Libraries no module here may import.

The wire formats this reads are small and are decoded by hand precisely
so that a package whose claim is that it is not the engine does not
depend on the engine. `apps/api` bans these names in prose; this bans
them as imports, which is the failure that would actually matter.
"""

EXPECTED_MODULE_COUNT = 11
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


def test_the_scan_finds_every_module_it_should() -> None:
    """Guard the scan. Everything below ranges over this."""
    found = modules()

    assert len(found) == EXPECTED_MODULE_COUNT, (
        f"Expected {EXPECTED_MODULE_COUNT} modules under {PACKAGE}, found {sorted(found)}. "
        "Raise the pin in the same commit, once you have confirmed the rules below see it."
    )


def test_every_module_is_placed_on_one_side_or_named_as_joining_them() -> None:
    """A module nobody classified is a module no rule below constrains."""
    classified = ENGINE_SIDE | AROC_SIDE | CONTRACT | JOINS_THEM

    assert set(modules()) == classified, (
        "A module is missing from the sets in this file, so no rule below applies to it: "
        f"{sorted(set(modules()) ^ classified)}"
    )


@pytest.mark.parametrize("name", sorted(AROC_SIDE))
def test_a_module_that_talks_to_aroc_names_no_engine_module(name: str) -> None:
    """The rule that was already broken once.

    An import here is how a second engine stops being a translator and
    starts being a fork.
    """
    reached = imports_of(modules()[name]) & ENGINE_SIDE

    assert not reached, (
        f"`{name}` talks to AROC and imports {sorted(reached)}, which reads one engine. "
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


@pytest.mark.parametrize("name", sorted(CONTRACT))
def test_the_contract_depends_on_neither_side(name: str) -> None:
    """A vocabulary that imported one side would not be shared, it would
    belong to that side."""
    reached = imports_of(modules()[name]) & (ENGINE_SIDE | AROC_SIDE)

    assert not reached, f"`{name}` is the shared vocabulary and imports {sorted(reached)}."


def test_only_one_module_joins_the_two_sides() -> None:
    """`wire` is findable because it is the only one, and the split is
    only as good as that being true."""
    joiners = {
        name
        for name, tree in modules().items()
        if name not in {"__init__", "__main__"}
        and imports_of(tree) & ENGINE_SIDE
        and imports_of(tree) & AROC_SIDE
    }

    assert joiners == {"wire"}, f"Expected only `wire` to name both sides, found {sorted(joiners)}."


@pytest.mark.parametrize("name", sorted(set(modules())))
def test_no_module_imports_an_engine_library(name: str) -> None:
    """The dependency this package refuses, and the reason `sources`
    decodes a published frame by hand."""
    reached = outside_imports(modules()[name]) & ENGINE_LIBRARIES

    assert not reached, f"`{name}` imports {sorted(reached)}, which is an engine."


@pytest.mark.parametrize("name", sorted(set(modules())))
def test_no_module_imports_aroc_itself(name: str) -> None:
    """Separate deployables, and the separation is the interpreter's rule
    rather than a convention only while this passes."""
    assert "aroc" not in outside_imports(modules()[name]), (
        f"`{name}` imports `aroc`. This is a client of that API over HTTP, and a "
        "reporter that can reach the model directly is not a separate deployable."
    )


def test_the_engine_library_ban_would_catch_something() -> None:
    """A banned-name check that matched nothing would pass on an empty
    list as readily as on a clean tree."""
    pretend = ast.parse("import bluesky\nfrom aroc.execution import Run\n")

    assert outside_imports(pretend) & ENGINE_LIBRARIES == {"bluesky"}
    assert "aroc" in outside_imports(pretend)
