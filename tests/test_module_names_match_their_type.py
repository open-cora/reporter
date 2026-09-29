"""A module that defines a type is named after it.

The keeper carries this rule and states the argument for it: the directories
it enforced were the only ones that stayed consistent, and every directory
it did not enforce drifted. The conductor is the evidence from the other
side, where a seam rename left an adapter module named for a Protocol that
no longer existed and nothing went red.

The rule is not that a filename carries a provider or a capability in an
agreed slot. It is that a reader who opens a file finds the type its name
promised. That is decidable, which is why it can be enforced, and being
enforced is the only property that has ever kept a directory consistent.

## What counts as a match

A module matches when a public type it defines snake-cases to:

  - the filename                  `session.py` -> `Session`
  - the folder plus the filename  `config.py` -> `ReporterConfig`
  - the filename as a prefix or suffix of the type
  - the singular of a plural filename  `outcomes.py` -> `Outcome`

## Why a plural filename counts, and why a type alias is a type

This package names a module for a family and puts the family's members in
it. `outcomes.py` holds `Outcome` and `intents.py` holds `Intent`, and both
are unions rather than classes. A rule reading only class statements would
call those modules nameless, and one without the plural form would still
miss them, so the two forms are load-bearing here rather than ornamental.

A plural matches its own singular only, so the relaxation cannot pass a
module holding an unrelated type.

## What this rule did not have to change

Nothing. Every module in this package either names a type it defines or is
declared below, which is not true of its two sibling projects: each had one
adapter named after the service it dials rather than after the adapter it
holds. This package renamed its seams to capabilities earlier than they
did, and its adapter classes followed at the same time, so the names this
rule asks for were already there when the rule arrived.

`adapters/store_http.py` is the one to read carefully. It passes on
`StoreHttpClient`, the Protocol describing the client it is handed, not on
`HttpLocating`, the adapter it exists to provide. The name is not lying, so
the rule is satisfied, but a reader should know the match is incidental.

## What the rule does not apply to

A module with no public type is a function namespace. There is no type to
be named after, and demanding one would invent a class per module. Error
and response classes are not the subject either, so a module exporting
functions and one error class is still a namespace.

That leaves modules that DO export public types and are still not about any
one of them. Those are declared below, and an entry costs a line of
reasoning.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from tests._tracked import PROJECT_ROOT, tracked_source_files

if TYPE_CHECKING:
    from pathlib import Path

NAMESPACE_MODULES: frozenset[str] = frozenset(
    {
        # The entrypoint. Exports `Tally`, the counts a run comes to, and
        # `Transport`, the intersection of the two client shapes the two
        # adapters ask for. Both exist so the command can wire a process
        # together, which is the thing the module is.
        "__main__.py",
        # The outward seams plus the two values that travel through them. A
        # family whose members are deliberately unlike each other: there is
        # no `Seam` type, because Protocols sharing no verb have nothing to
        # put on one.
        "seams.py",
        # Two capabilities against one service, `HttpReporting` and
        # `HttpFiling`, kept apart because a deployment switches them on
        # separately and one object would have to refuse half of itself.
        # Neither is the subject, and the client shape and the refusal
        # translation they share are why they sit in one file.
        "adapters/keeper_http.py",
        # Named for one engine's document grammar rather than for
        # `Translator`, the machine that reads it. A second engine writes a
        # sibling in this directory, and two modules both defining
        # `Translator` is what naming the file after the class would cost.
        "adapters/bluesky_documents.py",
    }
)
"""Modules that export a public type and are still not about one of them.

Separate from the automatic exemption for modules with no public type at
all. An entry here is a claim that the types present are a function's
arguments, its result, a family with no head, or the machinery of a subject
the filename names better than any class in it does.
"""

_NOT_A_SUBJECT = ("Error", "Response")
"""Type-name suffixes that never make a module type-shaped.

Nearly every module here raises something, and each adapter describes the
HTTP response it reads. A module exporting one adapter and three error
classes is not a module about an error.
"""


def _snake(name: str) -> str:
    out: list[str] = []
    for i, char in enumerate(name):
        boundary = (
            char.isupper()
            and i > 0
            and not (name[i - 1].isupper() and (i + 1 >= len(name) or name[i + 1].isupper()))
        )
        if boundary:
            out.append("_")
        out.append(char.lower())
    return "".join(out)


def _subject_types(tree: ast.Module) -> list[str]:
    """Public classes and type aliases defined at module level."""
    names: list[str] = []
    for node in tree.body:
        match node:
            case ast.ClassDef(name=str() as name):
                names.append(name)
            case ast.TypeAlias(name=ast.Name(id=str() as name)):
                names.append(name)
            case ast.AnnAssign(target=ast.Name(id=str() as name)) if _is_alias(node.value):
                names.append(name)
            case ast.Assign(targets=[ast.Name(id=str() as name)]) if _is_alias(node.value):
                names.append(name)
            case _:
                continue
    return [n for n in names if not n.startswith("_") and not n.endswith(_NOT_A_SUBJECT)]


def _is_alias(value: ast.expr | None) -> bool:
    """A union or a bare name on the right of an assignment is a type alias.

    `Outcome = Relayed | Kept` is one and `DEFAULT_TIMEOUT = 30.0` is not.
    Reading the right-hand side is what separates them, because both are a
    name bound at module level and nothing else distinguishes the two.
    """
    match value:
        case ast.BinOp(op=ast.BitOr()):
            return True
        case ast.Name(id=str() as referenced):
            return referenced[:1].isupper()
        case ast.Subscript(value=ast.Name()):
            return True
        case _:
            return False


def _matches(type_name: str, path: Path) -> bool:
    snake = _snake(type_name)
    stem, folder = path.stem, path.parent.name
    return (
        snake == stem
        or snake == f"{folder}_{stem}"
        or snake.endswith(f"_{stem}")
        or snake.startswith(f"{stem}_")
        or (stem.endswith("s") and snake == stem[:-1])
    )


def test_every_module_defining_a_type_is_named_after_one_of_them() -> None:
    offenders: list[str] = []
    for path in sorted(tracked_source_files()):
        relative = path.relative_to(PROJECT_ROOT / "src" / "reporter")
        if path.name == "__init__.py" or str(relative) in NAMESPACE_MODULES:
            continue
        types = _subject_types(ast.parse(path.read_text(encoding="utf-8")))
        if not types:
            continue
        if not any(_matches(name, path) for name in types):
            offenders.append(f"{relative}: defines {types}, named after none of them")
    assert not offenders, (
        "A module defining a public type must be named after one of them. Either "
        "rename the module to the type a reader will find in it, or add it to "
        "NAMESPACE_MODULES with a line saying why the types it holds are not its "
        "subject:\n  " + "\n  ".join(offenders)
    )


def test_every_namespace_module_entry_still_names_a_tracked_file() -> None:
    """An exemption outlives the file it was written for, and then hides a rule.

    A stale entry is worse than a missing one: it exempts nothing, so
    nothing fails, and the next module to take that path inherits an
    exemption written about a file that no longer exists.
    """
    source = PROJECT_ROOT / "src" / "reporter"
    missing = sorted(entry for entry in NAMESPACE_MODULES if not (source / entry).is_file())
    assert not missing, (
        "NAMESPACE_MODULES names files this project no longer has. Remove the "
        f"entry, or correct the path:\n  {chr(10).join(missing)}"
    )
