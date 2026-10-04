"""A module that declares an `__all__` lists everything public it defines.

Declaring one is optional here and several modules declare none, which
says the module has no curated surface and is a position this leaves
alone. Declaring an incomplete one says something false: that the names
in it are the surface, when something public is missing from the list.

This is the set-shaped half of a failure that keeps happening. A new
class lands everywhere it appears on its own, in the definition, at the
call, in the tests, in the prose, and is dropped in the one place things
appear as a collection. Nothing breaks, because an import reaches past
`__all__` and a star-import is not how anything here loads anything.

Five modules across this tree were wrong when this was written, two of
them lost by commits from the same week as the classes they omitted.
Counting them took a few lines and finding them by reading had not
happened in months.

Private names are skipped, and so is anything imported rather than
defined, because re-exporting is a choice and this rule is about what a
module makes and then fails to mention.
"""

from __future__ import annotations

import ast

import pytest

from tests._tracked import PROJECT_ROOT, tracked_source_files

EXPECTED_DECLARING_MODULES = 14
"""How many modules here declare an `__all__`.

Pinned for the usual reason: a rule ranging over nothing passes, and a
move or a rename is what empties it. Raise it when a module gains one.
"""


def _declared(tree: ast.Module) -> set[str] | None:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
        ):
            return {
                element.value
                for element in getattr(node.value, "elts", [])
                if isinstance(element, ast.Constant) and isinstance(element.value, str)
            }
    return None


def _defined(tree: ast.Module) -> set[str]:
    return {
        node.name
        for node in tree.body
        if isinstance(node, ast.ClassDef | ast.FunctionDef) and not node.name.startswith("_")
    }


def _declaring() -> list[tuple[str, set[str], set[str]]]:
    found: list[tuple[str, set[str], set[str]]] = []
    for path in sorted(tracked_source_files()):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        declared = _declared(tree)
        if declared is None:
            continue
        found.append((str(path.relative_to(PROJECT_ROOT)), declared, _defined(tree)))
    return found


def test_the_scan_finds_every_module_that_curates_a_surface() -> None:
    found = _declaring()
    assert len(found) == EXPECTED_DECLARING_MODULES, (
        f"found {len(found)} modules declaring __all__ and expected "
        f"{EXPECTED_DECLARING_MODULES}: {[where for where, _, _ in found]}"
    )


@pytest.mark.parametrize("module", _declaring(), ids=lambda m: m[0])
def test_a_module_that_declares_a_surface_leaves_nothing_public_off_it(
    module: tuple[str, set[str], set[str]],
) -> None:
    where, declared, defined = module
    assert not defined - declared, (
        f"{where} defines {sorted(defined - declared)} and does not list them in __all__, "
        "so its declared surface is narrower than what it makes"
    )
