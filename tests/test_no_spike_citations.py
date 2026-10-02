"""A published project may not cite a spike.

A spike is a program written to settle one question and then abandoned.
Nothing re-runs it, nothing keeps it working, and the packages it drove move
underneath it, so a measurement one produced is a note from an afternoon
rather than a standing fact. The directory holding them also sits at the
root of the development tree, which reaches that checkout and none of the
repositories published from it, so a citation here points at something a
reader of this project cannot open.

The development tree's own pages may cite them freely. This rule is about
what ships.

## Why a word and not a path

The paths are already gone once. One commit deleted the spikes and rewrote
every citation in the tree from a path to the bare phrase "a spike", and
when the spikes came back three days later the restoration could not find
these: the path had been the handle. The citations that survived were
invisible to any search for the directory, and were found only by reading.
A word survives that, which is why this refuses one.

## What a claim becomes instead

The mechanism, stated as what holds rather than as what was once observed.
"SIGKILL offers no hook" needs no witness. "A spike measured that SIGKILL
offers no hook" cites one that does not ship. Where a sentence carried a
count, the count goes and the reason it mattered stays.

## What this does not reach

The enumerators below are the ones the sibling prose rules share, and they
cover tracked `.py` and `.md`. A citation in `pyproject.toml` or another
config file is not seen, and one was: widening the enumerator would change
what every rule sharing it scans, so the gap is recorded here rather than
closed from this file.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from tests._tracked import (
    tracked_other_python_files,
    tracked_prose_files,
    tracked_source_files,
    tracked_test_files,
)

if TYPE_CHECKING:
    from pathlib import Path

_PATTERN = re.compile(r"\bspikes?\b", re.IGNORECASE)
"""Word-bounded, because the bar is a word with no other meaning here.

Matching on a substring would hit nothing in this tree today and would hit
`spiked` or a spike in a signal the moment somebody wrote one, which is how
a rule that fires on ordinary prose gets excepted into uselessness.
"""

_THIS_FILE = "test_no_spike_citations.py"
"""The one file excluded, because it has to name what it refuses."""

_FIXTURE_PAYLOAD = 'raise RuntimeError("the spike broke this run on purpose")'
"""The one line this rule permits, in the two collectors, permanently.

That string is recorded three times across `tests/documents.json` and
`tests/nodes.json`, once as the engine's own stop reason. Script and capture
agreeing about it is the thing the capture is evidence of, so changing one
without the other makes them disagree, and hand-editing a recording defeats
what a recording is for. Re-capturing would put a different agreed string in
both places and need this exemption again, which is why it is permanent
rather than pending.

It cites nothing. No measurement is claimed; the word is a payload.
"""


def _offenders(paths: frozenset[Path]) -> list[str]:
    hits: list[str] = []
    for path in sorted(paths):
        if path.name == _THIS_FILE:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _PATTERN.search(line) and line.strip() != _FIXTURE_PAYLOAD:
                hits.append(f"{path.name}:{lineno}: {line.strip()}")
    return hits


def test_the_scan_catches_a_citation_and_leaves_ordinary_prose_alone() -> None:
    """Both halves matter. A substring scan would fire on words like `spiked`."""
    assert _PATTERN.search("a spike measured this")
    assert _PATTERN.search("the two spikes disagree")

    assert not _PATTERN.search("a spiked reading")
    assert not _PATTERN.search("the SPIKEY_CONSTANT name")


def test_no_tracked_file_cites_a_spike() -> None:
    hits = _offenders(
        tracked_source_files()
        | tracked_test_files()
        | tracked_other_python_files()
        | tracked_prose_files()
    )
    assert not hits, (
        "A published file cites a spike. A spike is not re-run and does not "
        "ship with this project, so a claim resting on one cannot be checked "
        "by a reader. State the mechanism instead:\n" + "\n".join(hits)
    )
