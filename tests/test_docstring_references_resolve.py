"""A docstring may not name code or files that do not exist.

Backticks mean "this is a symbol". A reader who cannot find a backticked
name has no way to tell a name they have missed from a name that is not
there, so every dangling reference costs a search that ends in nothing.

Two rules, both decidable:

  - A backticked name whose shape says it is code must be bound somewhere
    in `src` or `tests`, or be declared in one of the two sets below.
  - A file path cited in a docstring must exist in this project.

Neither can see a wrong explanation of a real symbol. They catch the
cheaper failure, which is prose that refers to nothing at all.

## Why this project has its own copy

The rule is stated on this project's conventions page, which said it was
enforced before anything enforced it. That is the defect the same page
warns about two sections earlier: a rule falsely believed to be enforced
is worse than no rule, because nobody looks twice at it.

The scan is scoped to this project rather than to the checkout around it,
which is what makes it worth having. Prose here cited a sibling directory
for a long time, and such a citation resolves for exactly as long as the
sibling is next door.
"""

from __future__ import annotations

import ast
import builtins
import itertools
import re
from typing import TYPE_CHECKING

from tests._tracked import (
    PROJECT_ROOT,
    tracked_file_basenames,
    tracked_source_files,
    tracked_test_files,
)

if TYPE_CHECKING:
    from pathlib import Path

EXTERNAL_NAMES: frozenset[str] = frozenset(
    {
        # The keeper's class holding the two metadata keys. Real, in
        # another project, and spelled the same on both sides on purpose:
        # each side pins the literals, so one moving alone turns a test
        # red rather than a run.
        "EngineReport",
    }
)
"""Names that are real, but defined outside this project.

Declared rather than pattern-matched: an unknown name is a defect by
default, and admitting one should cost a line of evidence. Builtins are
admitted separately, since the builtins module enumerates them already.
"""

PROSPECTIVE_NAMES: frozenset[str] = frozenset(
    {
        # Worked-example test names inside the rule that judges test names.
        # Each is an input that rule accepts or refuses, so defining them
        # would mean defining the thing the example exists to describe.
        "test_decide_emits_x",
        "test_handler_works",
        # Three things this project had and removed, each named so the
        # prose can say what went and why. Requiring them to exist would
        # undo the removals they describe.
        "plan_ids",
        "ReportRun",
        "Recorded",
    }
)
"""Names this project deliberately does not define.

Distinct from `EXTERNAL_NAMES`, which are real elsewhere. These are real
nowhere: a shape some future module should adopt, a stand-in inside a
worked example, or an alternative the prose rejects by name. Each costs a
line here, so an entry is a decision rather than a way past the check.
"""

_SPAN = re.compile(r"`([^`\n]+)`")
"""Anything between backticks, on one line.

The span is not the name. Prose writes a dotted attribute, a call and a
subscript, and the name a reader would go looking for is the head of each:
the part before the first dot, bracket or parenthesis. Matching the whole
span instead lets a reference to a class nothing defines go unnoticed,
hidden by whatever follows the dot.
"""

_NAME_SHAPES = (
    re.compile(r"^[A-Z][a-zA-Z0-9]*[a-z][a-zA-Z0-9]*$"),
    re.compile(r"^_?[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+$"),
    re.compile(r"^_[A-Za-z][A-Za-z0-9_]*$"),
    re.compile(r"^_?[a-z][a-z0-9]*(?:_[a-z0-9]+)+$"),
)
"""The four shapes a head must have before it is worth resolving: CamelCase,
a screaming-snake constant, a leading-underscore private name, and a
snake_case name.

Everything else between backticks is left alone, because prose backticks
plain words, record fields, HTTP verbs and header values too. The constant
shape needs at least one underscore because a bare uppercase token is
usually a protocol word rather than a constant this project declares, and
every constant it does declare carries one. The snake_case shape needs one
for the same reason.
"""

_FILE_PATH = re.compile(r"`?\b([A-Za-z0-9_./-]+\.(?:py|sql|md|toml|yml|yaml|cff))\b`?")

EXTERNAL_FILES: frozenset[str] = frozenset(
    {
        # The configuration an operator writes and passes on the command
        # line. Named in the usage lines, which is where a reader needs to
        # see it, and a file this project must not ship: it holds a base
        # URL and a token.
        "reporter.toml",
    }
)
"""Files a docstring may name although this project does not hold them.

The sibling of `EXTERNAL_NAMES`, for paths rather than symbols, and kept
as small for the same reason: a citation nobody can follow is the defect,
so admitting one should cost a line saying who does hold it.
"""


def _cited_names(doc: str) -> list[str]:
    """Heads of every backticked span whose shape says it names code."""
    heads: list[str] = []
    for span in _SPAN.findall(doc):
        span = span.strip()
        # A span with a space inside it is a phrase, not a reference. Only a
        # single token can be looked up.
        if not span or " " in span:
            continue
        head = re.split(r"[.(\[]", span, maxsplit=1)[0]
        if head and any(shape.match(head) for shape in _NAME_SHAPES):
            heads.append(head)
    return heads


def _all_python_files() -> list[Path]:
    return sorted(tracked_source_files() | tracked_test_files())


def _defined_names() -> frozenset[str]:
    """Every name this project binds anywhere.

    Classes, functions, module stems, folder names, assignments,
    parameters, keyword arguments, attributes, imported symbols and string
    literals.

    Deliberately over-inclusive. The rule is about prose that refers to
    nothing, so admitting a name that exists in some other sense costs far
    less than a false failure on a real one.
    """
    names = set(dir(builtins)) | EXTERNAL_NAMES | PROSPECTIVE_NAMES
    for path in _all_python_files():
        names.add(path.stem)
        names.update(path.relative_to(PROJECT_ROOT).parts[:-1])
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            match node:
                case ast.ClassDef() | ast.FunctionDef() | ast.AsyncFunctionDef():
                    names.add(node.name)
                case ast.Name(ctx=ast.Store()):
                    names.add(node.id)
                case ast.arg():
                    names.add(node.arg)
                case ast.keyword(arg=str() as keyword_name):
                    names.add(keyword_name)
                case ast.Attribute():
                    names.add(node.attr)
                case ast.Constant(value=str() as text):
                    # A string literal in the same file makes the name real:
                    # record fields, `Literal[...]` arms and dict keys are
                    # code, even though they are not definitions.
                    names.add(text)
                case ast.TypeVar():
                    names.add(node.name)
                case ast.Import() | ast.ImportFrom():
                    names.update((a.asname or a.name).split(".")[-1] for a in node.names)
                case _:
                    pass
    return frozenset(names)


def _docstrings(path: Path) -> list[str]:
    """Every docstring in the file, attribute docstrings included.

    `ast.get_docstring` covers modules, classes and functions. It does not
    cover the bare string after an assignment, which this project uses for
    constants, and those are the docstrings most likely to name a constant.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if doc := ast.get_docstring(node):
            docs.append(doc)
        # The four node types above are also the four that carry a body of
        # statements, so walking them covers every place an attribute
        # docstring can sit and keeps `node.body` a typed list.
        for assignment, following in itertools.pairwise(node.body):
            if not isinstance(assignment, ast.Assign | ast.AnnAssign):
                continue
            match following:
                case ast.Expr(value=ast.Constant(value=str() as text)):
                    docs.append(text)
                case _:
                    pass
    return docs


def test_the_citation_scan_reads_something() -> None:
    """Guard the enumeration: no files means no rule."""
    assert _all_python_files(), "No Python file scanned."
    assert tracked_file_basenames(), "No tracked file to resolve a citation against."


def test_the_head_of_a_span_is_what_gets_resolved() -> None:
    """A dotted or called span resolves by its head, not as a whole.

    Anchoring on the whole span is what lets a name nothing defines hide
    behind whatever follows it.
    """
    assert _cited_names("see `Missing.method()` for this") == ["Missing"]
    assert _cited_names("`_PRIVATE_BUDGET` and `_helper`") == ["_PRIVATE_BUDGET", "_helper"]

    # A plain word, a bare uppercase token and a phrase are not references.
    assert _cited_names("`records`, `POST`, `a phrase here`") == []


def test_docstring_names_resolve_to_a_definition_in_the_tree() -> None:
    defined = _defined_names()
    unresolved: list[str] = []
    for path in _all_python_files():
        for doc in _docstrings(path):
            for name in _cited_names(doc):
                if name not in defined:
                    unresolved.append(f"{path.relative_to(PROJECT_ROOT)}: `{name}`")
    assert not unresolved, (
        "Docstrings name symbols defined nowhere in src or tests. Either the "
        "name is wrong (rewrite the prose), or it is real and external (add "
        "it to EXTERNAL_NAMES with a comment saying where it lives):\n  "
        + "\n  ".join(sorted(unresolved))
    )


def test_docstring_file_citations_resolve_to_a_path_in_the_project() -> None:
    tracked = tracked_file_basenames()
    unresolved: list[str] = []
    for path in _all_python_files():
        for doc in _docstrings(path):
            for line in doc.splitlines():
                # A URL cites someone else's tree, not this one.
                if "http" in line or re.search(r"\b[a-z0-9-]+\.(?:com|org|io|net)/", line):
                    continue
                for cited in _FILE_PATH.findall(line):
                    basename = cited.split(":")[0].split("/")[-1]
                    if basename not in tracked and basename not in EXTERNAL_FILES:
                        unresolved.append(f"{path.relative_to(PROJECT_ROOT)}: {cited}")
    assert not unresolved, (
        "Docstrings cite files that do not exist in this project. A reader "
        "cannot follow them, so the claim they support cannot be checked:\n  "
        + "\n  ".join(sorted(unresolved))
    )
