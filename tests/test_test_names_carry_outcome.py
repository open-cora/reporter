"""Test function names state the property, not just the subject.

`test_<subject>_<scenario>_<expectation>`, and long is fine. A name that
stops at the subject tells a reader which code ran but not what was
supposed to be true of it, so a failure report names a function rather
than a broken promise.

The heuristic is deliberately loose: a minimum word count and a ban on
the vaguest endings. It catches `test_handler_works`, not every weak
name. A tighter rule would reject legitimate names and get suppressed,
which is worth less than a loose rule that holds.
"""

from __future__ import annotations

import ast

from tests._tracked import tracked_test_files

MIN_WORDS = 4
"""`test_` plus at least three more words. `test_decide_emits_x` clears it."""

VAGUE_ENDINGS = frozenset({"works", "ok", "correct", "good", "valid", "test"})
"""Endings that name no outcome.

`it` was in here and earned nothing. A name short enough for a trailing
`it` to be a hand-wave is already caught by the word count, so every name
this reached was one where `it` was an ordinary object pronoun: six of
them in the conductor's suite at once, all good names.
"""

NEGATORS = frozenset({"not", "never"})
"""Words that make a vague ending precise.

`test_a_schema_that_is_not_valid_is_refused` is a good name: "valid" is
the predicate being negated, not a hand-wave. Without this carve-out the
rule rejects it, which is the false positive that gets a rule suppressed
rather than obeyed.
"""


def _is_fixture(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Whether the function carries a pytest fixture decorator."""
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Attribute) and target.attr == "fixture":
            return True
        if isinstance(target, ast.Name) and target.id == "fixture":
            return True
    return False


def _weakness(name: str) -> str | None:
    """Why this name is weak, or None when it is not."""
    words = name.split("_")
    if len(words) < MIN_WORDS:
        return "too few words"
    if words[-1] in VAGUE_ENDINGS and words[-2] not in NEGATORS:
        return "vague ending"
    return None


def test_the_name_rule_catches_a_weak_name_and_passes_a_negated_one() -> None:
    """Both halves matter, and the second is why NEGATORS exists."""
    assert _weakness("test_handler") == "too few words"
    assert _weakness("test_register_thing_works") == "vague ending"

    assert _weakness("test_decide_emits_thing_defined_when_stream_is_empty") is None
    assert _weakness("test_a_schema_that_is_not_valid_is_refused") is None


def test_every_test_function_name_states_an_outcome() -> None:
    offenders: list[str] = []
    for path in sorted(tracked_test_files()):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if not node.name.startswith("test_"):
                continue
            if _is_fixture(node):
                # A fixture is not a test, even when it is `test_`-prefixed.
                # The prefix is worth fixing at the fixture, but it must not
                # be reported here as a weak test name.
                continue
            if weakness := _weakness(node.name):
                offenders.append(f"{path.name}:{node.lineno}: {node.name} ({weakness})")
    assert not offenders, "Test names that name a subject but not an outcome:\n" + "\n".join(
        offenders
    )
