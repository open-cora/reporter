"""The structural rules this package has, and checks that they hold.

Two rules, and they were one until the seams were cut apart.

The first is the split the reporter has always had. `intents` and
`outcomes` are the vocabulary, `session` acts on one intent, `relay` puts
a queue in front of it, and `seams` says what may be asked of the outside
world. Between them those five import the standard library and each
other, and nothing else. What that buys is that a second engine is a
module under `adapters/` rather than a rewrite.

The second is the one that arrived with `adapters/`. The core names a
capability by its Protocol and never an implementation, and `__main__` is
the one module that picks. That rule is why `Session` no longer takes a
one client object: what it takes is `Reporting`, and which service
answers is a sentence in the entrypoint.

Neither is visible in a diff. A single `from reporter.adapters...` in
`session.py` would work perfectly and would make a 0MQ socket a hard
dependency of acting on an intent. The split was already broken once
exactly that quietly, by a helper filed on the wrong side, and no test
failed because there was no test.

These read imports rather than running anything, which is why they are
cheap enough to keep.

## Why the counts are pinned

Every check below ranges over a set discovered from disk. A rename, a
move or a typo silently shrinks that set, and a rule ranging over nothing
passes. The pins turn "found nothing to check" into a failure. Raise one
only after confirming the rule now sees what you added, never to make a
red run green.
"""

import ast
import sys
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "reporter"
ADAPTERS_DIR = PACKAGE / "adapters"

CORE = frozenset({"seams", "intents", "outcomes", "session", "relay"})
"""The modules a delivery is acted on in. Standard library and each other.

`seams` is core rather than a tier of its own. A Protocol describing what
this reporter needs is written in the same vocabulary as the thing that
needs it, and filing it outside would suggest the capability belongs to
whatever implements it.
"""

ENTRYPOINT = frozenset({"__init__", "__main__"})
"""The two the rules below treat specially.

`__main__` is the one module allowed to name an adapter, because
something has to. `__init__` gets its own check rather than this one,
because what matters there is narrower: importing this package must not
require any adapter's library.
"""

EXPECTED_CORE_MODULES = 5
"""How many files `CORE` should find. Moving one without saying so fails here."""

EXPECTED_OUTER_MODULES = 1
"""Root modules that are neither the core nor an entrypoint.

One: `config`, which reads a file. It is held to the core's rule, because
a loader that imported an adapter would be a loader only one transport
could ever use.
"""

EXPECTED_ADAPTERS = 5
"""Adapter modules under `adapters/`, excluding its `__init__`.

Five: one engine's documents, a 0MQ subscription, a capture on disk, the
keeper's HTTP API and a store's. The checks below were confirmed to range
over each when it arrived, which is what raising this number is supposed
to mean.
"""

ENGINE_LIBRARIES = frozenset({"bluesky", "ophyd", "databroker", "epics", "caproto", "tomoscan"})
"""Libraries no module here may import, adapters included.

The wire formats this reads are small and are decoded by hand precisely
so that a package whose claim is that it is not the engine does not
depend on the engine. `apps/keeper` bans these names in prose; this bans
them as imports, which is the failure that would actually matter.

Adapters are inside the ban rather than outside it, and that is the one
place these rules are stricter than `apps/conductor`. The reason is a
measurement rather than a principle: reading a published frame through
the engine's own library drags in numpy to a process whose job is to
forward six strings. An engine adapter that needs the library is a
decision to make here, out loud.
"""

STORE_LIBRARIES = frozenset({"tiled"})
"""Store clients no module here may import, for a different reason.

The engine ban is about identity. This one is about what the client
buys: reading one node through the store's client and off its raw HTTP
surface gives the same address, so the client would buy insulation from
an envelope that two fields are read out of,
and cost a dependency.

Separate from the set above rather than merged into it, because the two
bans would be lifted for different reasons and a merged set would hide
which argument had stopped holding.
"""

ENGINE_WORDS = frozenset({"document", "descriptor", "datum", "runstart", "runstop"})
"""Engine vocabulary that may not appear in a name in the core.

The import rules keep the core from reaching an adapter. This keeps the
engine's words from drifting across while the imports stay clean, which
is how the leak actually happened: `relay` queued a thing it never opens
and called it a `document`, so the module that knows least about the
engine used its vocabulary in a signature.

**Identifiers only, never prose.** Several passages have to say
"document" to make their point, and each is explaining this very
boundary. A prose ban would need a line-level allow-list, which is
brittle and would be edited to silence a failure. A name is a flat fact,
so the rule is flat.

The adapters are exempt because naming the engine is their job, and the
two entrypoints because `documents_into` is chosen there on purpose.
"""


def _core_paths() -> list[Path]:
    return sorted(PACKAGE / f"{name}.py" for name in CORE)


def _outer_paths() -> list[Path]:
    """Everything at the package root that is neither core nor an entrypoint."""
    return sorted(
        path
        for path in PACKAGE.glob("*.py")
        if path.stem not in CORE and path.stem not in ENTRYPOINT
    )


def _adapter_paths() -> list[Path]:
    return sorted(p for p in ADAPTERS_DIR.glob("*.py") if p.name != "__init__.py")


def _all_paths() -> list[Path]:
    return sorted(PACKAGE.glob("*.py")) + sorted(ADAPTERS_DIR.glob("*.py"))


def _imported_roots(path: Path) -> set[str]:
    """Every import in a module, by the name it was written with.

    `from reporter.adapters.keeper_http import X` yields
    `reporter.adapters.keeper_http` rather than `reporter`, because the
    checks below need to tell a core-to-core import from a
    core-to-adapter one, and the root alone cannot.
    """
    roots: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module)
    return roots


def _identifiers_of(tree: ast.Module) -> set[str]:
    """Every name a module declares, lowercased.

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


def test_every_core_module_is_on_disk() -> None:
    """Guard the enumeration, so the checks below cannot pass vacuously."""
    missing = [p.name for p in _core_paths() if not p.exists()]
    assert not missing, f"CORE names modules that are not there: {missing}"
    assert len(_core_paths()) == EXPECTED_CORE_MODULES


def test_every_adapter_is_on_disk() -> None:
    """The same guard for the other side of the rule."""
    found = _adapter_paths()
    assert found, "No adapter module found, so the adapter checks examine nothing."
    assert len(found) == EXPECTED_ADAPTERS, f"Adapter count moved: {[p.name for p in found]}"


def test_every_module_outside_the_core_is_accounted_for() -> None:
    """The same guard, for the modules that belong to neither side."""
    found = _outer_paths()
    assert len(found) == EXPECTED_OUTER_MODULES, (
        f"Root modules outside the core moved: {[p.name for p in found]}. Each one is "
        "held to the core's rule, so a new one is a deliberate addition rather than a "
        "number to raise."
    )


@pytest.mark.parametrize("path", _core_paths(), ids=lambda p: p.name)
def test_core_module_imports_nothing_outside_the_standard_library(path: Path) -> None:
    outsiders = sorted(
        root
        for root in _imported_roots(path)
        if root.split(".")[0] not in sys.stdlib_module_names and root.split(".")[0] != "reporter"
    )
    assert not outsiders, (
        f"{path.name} imports {outsiders}, so acting on an intent now needs it "
        "installed. A library belonging to one outside system goes in "
        "reporter/adapters/, behind a Protocol in seams.py."
    )


@pytest.mark.parametrize("path", _core_paths(), ids=lambda p: p.name)
def test_core_module_imports_no_adapter(path: Path) -> None:
    reached = sorted(root for root in _imported_roots(path) if root.startswith("reporter.adapters"))
    assert not reached, (
        f"{path.name} imports {reached}. The core names a seam by its Protocol "
        "and never by an implementation; the entrypoint chooses which one."
    )


@pytest.mark.parametrize("path", _outer_paths(), ids=lambda p: p.name)
def test_a_module_outside_the_core_is_held_to_the_core_rule(path: Path) -> None:
    reached = sorted(
        root
        for root in _imported_roots(path)
        if root.startswith("reporter.adapters")
        or (root.split(".")[0] not in sys.stdlib_module_names and root.split(".")[0] != "reporter")
    )
    assert not reached, (
        f"{path.name} imports {reached}. It sits above reporter/adapters/ and names a "
        "seam by its Protocol, the way the core does; __main__ is where an "
        "implementation is chosen."
    )


def test_the_package_root_imports_no_adapter() -> None:
    """`import reporter` must not require any outside system's library."""
    reached = sorted(
        root
        for root in _imported_roots(PACKAGE / "__init__.py")
        if root.startswith("reporter.adapters")
    )
    assert not reached, (
        f"reporter/__init__.py imports {reached}, which makes that adapter's "
        "library a hard dependency of importing this package at all."
    )


def test_the_adapters_package_imports_nothing() -> None:
    """Its `__init__` stays empty of imports for the same reason.

    A re-export there would make `import reporter.adapters` pull in every
    adapter's library, which is the hard dependency this rule exists to
    avoid, reintroduced one level down.
    """
    assert not _imported_roots(ADAPTERS_DIR / "__init__.py")


@pytest.mark.parametrize("path", _adapter_paths(), ids=lambda p: p.name)
def test_adapter_imports_no_sibling_adapter(path: Path) -> None:
    """An adapter may use the core. It may not reach into another adapter.

    Two adapters that shared code would be two outside systems joined
    through this package, and whichever one imported the other would drag
    its library along.
    """
    siblings = sorted(
        root
        for root in _imported_roots(path)
        if root.startswith("reporter.adapters") and not root.endswith(path.stem)
    )
    assert not siblings, f"{path.name} imports sibling adapters {siblings}."


@pytest.mark.parametrize("path", _core_paths() + _outer_paths(), ids=lambda p: p.name)
def test_a_module_in_the_core_keeps_engine_words_out_of_its_names(path: Path) -> None:
    """The vocabulary half of the split, which the import half missed.

    `relay` held `document` in two signatures while importing nothing
    from the engine side, so every import rule passed.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    reached = {
        identifier
        for identifier in _identifiers_of(tree)
        for word in ENGINE_WORDS
        if word in identifier
    }
    assert not reached, (
        f"`{path.name}` is in the core and declares {sorted(reached)}. "
        "What arrives is a `delivery` and its opaque half is a `payload`; a "
        "second engine sends neither documents nor descriptors."
    )


@pytest.mark.parametrize("path", _all_paths(), ids=lambda p: p.name)
def test_no_module_imports_an_engine_library(path: Path) -> None:
    """The dependency this package refuses, and the reason a published
    frame is decoded by hand."""
    reached = sorted(
        root for root in _imported_roots(path) if root.split(".")[0] in ENGINE_LIBRARIES
    )
    assert not reached, f"`{path.name}` imports {reached}, which is an engine."


@pytest.mark.parametrize("path", _all_paths(), ids=lambda p: p.name)
def test_no_module_imports_a_store_library(path: Path) -> None:
    """The dependency found unnecessary rather than refused."""
    reached = sorted(
        root for root in _imported_roots(path) if root.split(".")[0] in STORE_LIBRARIES
    )
    assert not reached, f"`{path.name}` imports {reached}, which is a store client."


@pytest.mark.parametrize("path", _all_paths(), ids=lambda p: p.name)
def test_no_module_imports_the_keeper_itself(path: Path) -> None:
    """Separate deployables, and the separation is the interpreter's rule
    rather than a convention only while this passes."""
    reached = sorted(root for root in _imported_roots(path) if root.split(".")[0] == "keeper")
    assert not reached, (
        f"`{path.name}` imports `keeper`. This is a client of that API over HTTP, and a "
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

    declared = _identifiers_of(pretend)

    assert {word for word in ENGINE_WORDS if word in " ".join(declared)} == {
        "document",
        "descriptor",
    }
    assert "payload" in declared
    assert "other" not in declared


def test_the_library_bans_would_catch_something(tmp_path: Path) -> None:
    """A banned-name check that matched nothing would pass on an empty
    list as readily as on a clean tree."""
    pretend = tmp_path / "pretend.py"
    pretend.write_text(
        "import bluesky\nimport tiled.client\nfrom keeper.execution import Execution\n",
        encoding="utf-8",
    )

    roots = {root.split(".")[0] for root in _imported_roots(pretend)}

    assert roots & ENGINE_LIBRARIES == {"bluesky"}
    assert roots & STORE_LIBRARIES == {"tiled"}
    assert "keeper" in roots


def test_the_adapter_rule_would_catch_a_core_module_reaching_one(tmp_path: Path) -> None:
    """The rule the seams exist for, shown refusing the import that would
    undo them."""
    pretend = tmp_path / "pretend.py"
    pretend.write_text(
        "from reporter.adapters.keeper_http import HttpReporting\n", encoding="utf-8"
    )

    reached = [r for r in _imported_roots(pretend) if r.startswith("reporter.adapters")]

    assert reached == ["reporter.adapters.keeper_http"]
