"""No phase, iteration or audit tags in source or prose.

`Phase 8f-d`, `Iter B-3`, `slice 5g-c`, `audit-2026-05-20`: each names a
moment in a plan, and each rots the moment the plan moves. The current
code is what is true, and ordering lives in git history.

The check is literal and shape-based together, because the literal forms
are easy to avoid by accident while the shape, `6g-c` or `5g-a`, reads as
a coordinate and goes through review unnoticed.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from tests._tracked import tracked_prose_files, tracked_source_files, tracked_test_files

if TYPE_CHECKING:
    from pathlib import Path

_PATTERNS = (
    # Separator-agnostic: `Phase 8e`, `Phase-8e` and `Phase_8e` are one tag
    # wearing three coats.
    re.compile(r"\bPhase[\s_-]*\d", re.IGNORECASE),
    re.compile(r"\bIter(ation)?[\s_-]*[A-Z]-?\d", re.IGNORECASE),
    re.compile(r"\bslice\s+\d+[a-z]\b", re.IGNORECASE),
    re.compile(r"\baudit-20\d\d-\d\d-\d\d\b", re.IGNORECASE),
    # A bare plan coordinate such as 6g-c or 5g-a.
    re.compile(r"\b\d+[a-z]-[a-z]\b"),
    # A review-finding reference. The same rot as a phase tag and one step
    # worse: it points at a numbered finding in a document that does not
    # travel with the code, so a reader cannot look it up even in principle.
    re.compile(r"\bgate.review\b", re.IGNORECASE),
    re.compile(r"\b(impl|test|review)#\d+", re.IGNORECASE),
    # The finding codes themselves. Enumerated rather than generalized,
    # because the obvious generalization also swallows `RFC 9728`,
    # `PEP 258`, `HTTP 401` and `ISA-95`.
    re.compile(r"\b(GR|SEC|BLOCKING|RISK|FINDING)[\s_-]?[A-Z]?-?\d+\b"),
)


_THIS_FILE = "test_no_phase_markers.py"
"""The one file excluded, because it has to name what it refuses.

Scanning it fails on its own patterns and on its own worked examples. The
cost is that a real tag written into this file goes unseen, which is the
narrowest hole available: any file defining these forms has to spell them.
"""


def _offenders(paths: frozenset[Path]) -> list[str]:
    hits: list[str] = []
    for path in sorted(paths):
        if path.name == _THIS_FILE:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if any(pattern.search(line) for pattern in _PATTERNS):
                hits.append(f"{path.name}:{lineno}: {line.strip()}")
    return hits


def test_the_tag_scan_catches_a_tag_and_leaves_a_standard_alone() -> None:
    """Both halves matter. A scan that fired on `RFC 9728` would be suppressed."""
    assert _offenders_in("a note about Phase 3 here")
    assert _offenders_in("the 6g-c coordinate")
    assert _offenders_in("see gate-review F2")

    assert not _offenders_in("RFC 9728 and PEP 258 and HTTP 401")
    assert not _offenders_in("the ISA-95 levels")


def _offenders_in(line: str) -> bool:
    return any(pattern.search(line) for pattern in _PATTERNS)


def test_tracked_source_and_prose_carry_no_phase_markers() -> None:
    hits = _offenders(tracked_source_files() | tracked_test_files() | tracked_prose_files())
    assert not hits, (
        "Phase, iteration or audit tag in source or prose. Git log is the "
        "right home:\n" + "\n".join(hits)
    )
