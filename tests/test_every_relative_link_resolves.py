"""Every relative link in this project's prose points at a file that is there.

`mkdocs build --strict` already fails on a broken cross-link, and it is what
makes the documentation trustworthy. What it does not read is a page outside
the site: `README.md`, `CONTRIBUTING.md`, `SECURITY.md` and `CLAUDE.md` are
none of them in a nav, so a link from one of them is checked by nothing.

That gap has already cost something in this tree. When one project's pages
moved into its own directory, the pages left behind went on pointing at paths
that no longer existed. Three files, eight links, and every build stayed green
because none of those files is a page. They were found by reading.

This project is published as a repository of its own, so those four files are
the first thing a reader meets and the site is not where they start.

## What this checks and what it does not

The target file exists. Not the anchor after it: `mkdocs` verifies headings
for pages in a nav, and reimplementing that here would mean parsing headings
and slugifying them the same way the theme does, which is a copy of somebody
else's algorithm that goes stale silently. A link to the right file and a dead
anchor is a smaller defect than a link to nothing.

Absolute URLs are skipped. Checking them means network access from a test
suite, which trades a deterministic check for a flaky one.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from tests._tracked import PROJECT_ROOT, tracked_prose_files

if TYPE_CHECKING:
    from pathlib import Path

_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
"""An inline markdown link's target.

No whitespace in the capture, which drops the `[text](path "title")` form's
title rather than treating it as part of the path. Reference-style links are
not matched and are not used in this tier's pages.
"""

_SKIPPED_SCHEMES = ("http://", "https://", "mailto:", "ftp://")


def _unresolved(paths: frozenset[Path]) -> list[tuple[Path, int, str]]:
    """Every relative link in `paths` whose target is not on disk.

    Returns the pieces rather than a formatted line, so the check below can
    be shown to fire against a file of its own making. Formatting here would
    mean resolving against the tree root, and a file written to a temporary
    directory is not under it.
    """
    broken: list[tuple[Path, int, str]] = []
    for path in sorted(paths):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for target in _LINK.findall(line):
                if target.startswith(_SKIPPED_SCHEMES) or target.startswith("#"):
                    continue
                relative = target.split("#", 1)[0]
                if not relative:
                    continue
                if not (path.parent / relative).exists():
                    broken.append((path, lineno, target))
    return broken


def test_the_link_scan_finds_links_to_check() -> None:
    """Guard the derivation: a regex that stopped matching passes everything."""
    assert tracked_prose_files(), "No prose file scanned."
    found = sum(
        len(_LINK.findall(path.read_text(encoding="utf-8"))) for path in tracked_prose_files()
    )
    assert found > 10, f"Only {found} links found across this project's prose, which is too few."


def test_the_scan_catches_a_dead_link_and_leaves_a_url_alone(tmp_path: Path) -> None:
    """Both halves matter.

    Missing the first is the defect this file exists for. Failing the second
    would make every page citing a specification a failure, and a rule that
    fires on a good link gets suppressed rather than obeyed.
    """
    page = tmp_path / "page.md"
    page.write_text(
        "[gone](./nowhere.md)\n"
        "[site](https://example.org/thing)\n"
        "[anchor](#a-heading)\n"
        "[self](page.md)\n"
        "[deep](page.md#a-heading)\n",
        encoding="utf-8",
    )
    broken = _unresolved(frozenset({page}))
    assert broken == [(page, 1, "./nowhere.md")]


def test_every_relative_link_in_this_projects_prose_resolves() -> None:
    broken = _unresolved(tracked_prose_files())
    named = [
        f"{path.relative_to(PROJECT_ROOT)}:{lineno}: {target}" for path, lineno, target in broken
    ]
    assert not named, (
        "Prose links to a file that is not there:\n  "
        + "\n  ".join(named)
        + "\n\nThese pages sit outside the mkdocs nav, so a strict site build "
        "does not read them. This rule is what does."
    )
