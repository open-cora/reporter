"""No emoji anywhere in source or prose.

Comments, docstrings, log strings, error messages and documentation
alike. Emoji in source is a documented model tell that accumulates as
noise across reviews, and it has no place in a log line an operator
greps.

Scope is pictographic ranges only. Sweeping the arrows block as well
costs more than it is worth: a docstring drawing a mapping with a
maps-to arrow would fail a check named "no emoji", and a rule that
fails for a reason its name does not describe is one people learn to
suppress.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from tests._tracked import tracked_prose_files, tracked_source_files, tracked_test_files

if TYPE_CHECKING:
    from pathlib import Path

_EMOJI = re.compile(
    "["
    "\U0001f300-\U0001faff"  # pictographs, emoticons, transport, symbols
    "\U0001f000-\U0001f0ff"  # mahjong, dominoes, cards
    "\U0001f900-\U0001f9ff"  # supplemental symbols, faces, gestures
    "\u2600-\u27bf"  # misc symbols and dingbats
    "]"
)


def _offenders(paths: frozenset[Path]) -> list[str]:
    hits: list[str] = []
    for path in sorted(paths):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            found = _EMOJI.findall(line)
            if found:
                hits.append(f"{path.name}:{lineno}: {found!r} in {line.strip()}")
    return hits


def test_the_emoji_scan_would_catch_one() -> None:
    """Guard the pattern: a regex matching nothing is a rule matching nothing."""
    assert _EMOJI.findall("a rocket \U0001f680 here")
    assert not _EMOJI.findall("a plain line of prose")


def test_tracked_source_and_prose_carry_no_emoji() -> None:
    hits = _offenders(tracked_source_files() | tracked_test_files() | tracked_prose_files())
    assert not hits, "Emoji in source or prose:\n" + "\n".join(hits)
