"""The two places this project declares its version have to agree.

`pyproject.toml` is what a build reads and `CITATION.cff` is what a citation
reads, and nothing but this keeps them saying the same thing. A stale version
in the second does not break anything, which is the problem: it ends up in
somebody's bibliography, pointing at a release that was never cut.

The release tag is the third declaration and it is not checked here, because
it does not exist in the tree. The ordering that keeps all three in step is in
CONTRIBUTING.md: bump both files, publish, then tag what was published.

## Why this reads CITATION.cff by hand

It is YAML, and the obvious answer is a YAML parser. No project here declares
one: the library is present only as something pre-commit pulls in, so a test
importing it would depend on another tool's dependency tree. Declaring it
would mean adding a dependency to every project to read three strings, and
a strict typechecker then wants casts around everything the parser returns.

What is actually needed is three top-level scalars out of a file that is
machine-readable by construction. That is a line with no indentation, which
is a rule small enough to implement and, below, to show working.
"""

from __future__ import annotations

import re
import tomllib
from datetime import date

from tests._tracked import PROJECT_ROOT

CITATION = PROJECT_ROOT / "CITATION.cff"
PYPROJECT = PROJECT_ROOT / "pyproject.toml"

PROJECT_NAME = "reporter"
"""What this project is called, which is the name its repository carries.

Written out rather than read from `pyproject.toml`, because the check below
compares the citation's repository URL against it. Deriving both sides from
one source would let a copied file agree with itself.
"""

_SEMVER = re.compile(r"^\d+\.\d+\.\d+([-+][0-9A-Za-z.-]+)?$")


def citation_scalar(text: str, field: str) -> str | None:
    """A top-level scalar from CITATION.cff text, or None when absent.

    Top-level means the line starts at column zero. That is the whole rule,
    and it is what keeps a nested `version:` under `authors:` from being
    mistaken for the release version, which is the one way this could read
    the wrong string and still look right.

    Takes the text rather than the path so the checks below can be run
    against input of their own making.
    """
    prefix = f"{field}:"
    for line in text.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip().strip('"').strip("'")
    return None


def _cited(field: str) -> str | None:
    return citation_scalar(CITATION.read_text(encoding="utf-8"), field)


def _declared_version() -> str:
    with PYPROJECT.open("rb") as handle:
        project = tomllib.load(handle)
    version = project["project"]["version"]
    assert isinstance(version, str)
    return version


def test_the_citation_reader_finds_a_top_level_field_and_skips_a_nested_one() -> None:
    """Guard the reader: one that found nothing would compare None to None.

    The second half is the one worth having. `authors:` in a CITATION.cff is a
    list of mappings, and a reader keyed on the bare word would take a value
    from inside one and report it as the release version.
    """
    sample = "version: 1.2.3\nauthors:\n  - family-names: Somebody\n    version: 9.9.9\n"
    assert citation_scalar(sample, "version") == "1.2.3"
    assert citation_scalar(sample, "family-names") is None
    assert citation_scalar(sample, "absent") is None


def test_both_files_declare_a_version_this_check_can_read() -> None:
    """Guard the enumeration: an unreadable field makes every check below vacuous."""
    assert _cited("version"), f"{CITATION.name} declares no top-level version."
    assert _declared_version(), f"{PYPROJECT.name} declares no version."


def test_the_two_declared_versions_agree() -> None:
    cited, declared = _cited("version"), _declared_version()
    assert cited == declared, (
        f"{PYPROJECT.name} says {declared} and {CITATION.name} says {cited}. "
        "Both are declarations of the same release and a citation carrying the "
        "wrong one is repeated by everybody who cites it. Bump them together."
    )


def test_the_declared_version_is_a_version() -> None:
    declared = _declared_version()
    assert _SEMVER.match(declared), (
        f"{PYPROJECT.name} declares {declared!r}, which is not a version this "
        "project can be released under. A tag is cut from this string."
    )


def test_the_release_date_is_a_date_that_exists() -> None:
    """A citation carries the date a version was released, so it has to parse.

    `date.fromisoformat` is the check rather than a regex, because the shapes a
    regex lets through include the 31st of February.
    """
    released = _cited("date-released")
    assert released, f"{CITATION.name} declares no top-level date-released."
    try:
        date.fromisoformat(released)
    except ValueError as exc:
        raise AssertionError(
            f"{CITATION.name} gives date-released as {released!r}, which is not "
            f"a date: {exc}. It is read by citation tooling, not only by people."
        ) from exc


def test_the_citation_names_this_projects_own_repository() -> None:
    """These files are copied between projects, and a URL survives the copy.

    Every project here carries the same five metadata files and each was
    written by copying a sibling's. A repository URL is the field that looks
    right in every one of them and is wrong in all but the original.
    """
    url = _cited("repository-code")
    assert url, f"{CITATION.name} declares no top-level repository-code."
    assert url.rstrip("/").endswith(f"/{PROJECT_NAME}"), (
        f"{CITATION.name} points at {url}, which is not this project's "
        f"repository. A citation of {PROJECT_NAME} would send a reader "
        "somewhere else."
    )
