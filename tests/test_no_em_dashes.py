"""No em dashes or en dashes in source or prose.

Substitute a comma, a colon, a semicolon, or rephrase.

There is no allowlist, and that is the point. A tree that adopts this rule
after its prose is written needs a ratchet; this one was scrubbed before
the rule arrived, so the rule can simply hold. An allowlist added now would
start the ratchet anyway.

Source and prose both, and the prose half is the half that matters here.
This project's pages were assembled by hand out of a larger tree's, and
nothing checked the result until this existed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests._tracked import tracked_prose_files, tracked_source_files, tracked_test_files

if TYPE_CHECKING:
    from pathlib import Path

_EM_DASH = "\u2014"
_EN_DASH = "\u2013"


def _offenders(paths: frozenset[Path]) -> list[str]:
    hits: list[str] = []
    for path in sorted(paths):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _EM_DASH in line or _EN_DASH in line:
                hits.append(f"{path.name}:{lineno}: {line.strip()}")
    return hits


def test_the_dash_scan_reaches_both_source_and_prose() -> None:
    """Guard the enumeration: an empty file set makes the rule vacuous."""
    assert tracked_source_files(), "No source file scanned."
    assert tracked_prose_files(), "No prose file scanned."


def test_tracked_source_carries_no_em_dashes() -> None:
    hits = _offenders(tracked_source_files() | tracked_test_files())
    assert not hits, "Em or en dash in source:\n" + "\n".join(hits)


def test_tracked_prose_carries_no_em_dashes() -> None:
    hits = _offenders(tracked_prose_files())
    assert not hits, "Em or en dash in prose:\n" + "\n".join(hits)
