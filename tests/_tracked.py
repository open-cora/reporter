"""Git's view of this project, for the checks that range over all of it.

Every check that enumerates files goes through here rather than walking
the filesystem, and the reason is pre-commit. It stashes unstaged changes
to tracked files and never untracked ones, so during a hook run a
half-written module sits live on disk beside stashed edits to the file
that was going to import it. A filesystem walk sees that arrangement and
fails on it; git's tracked set sees what pre-commit is actually
evaluating.

The corollary is the trap, and it is worth stating because a green run
looks the same either way: a file git has never seen is invisible to
every check below. Stage new files before trusting one.

Rooted at the project rather than at the checkout, because this project
is one directory inside a larger tree today and a repository of its own
afterwards. Scoping to the directory means these checks already range
over exactly what the repository will hold, so a citation that will break
at the split breaks here instead.
"""

from __future__ import annotations

import os
import subprocess
from functools import cache
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
"""The directory holding `pyproject.toml`, and the root of the repository to be."""

SOURCE_ROOT = PROJECT_ROOT / "src" / "reporter"
TESTS_ROOT = PROJECT_ROOT / "tests"


def _ls_files(*pathspecs: str) -> list[str]:
    """Tracked paths under `PROJECT_ROOT`, relative to it.

    GIT_DIR and GIT_INDEX_FILE are stripped because pre-commit points them
    at its own staging area. Left in place inside a worktree they name the
    parent checkout's index, and the answer is then a list of the wrong
    repository's files.
    """
    env = {k: v for k, v in os.environ.items() if k not in {"GIT_DIR", "GIT_INDEX_FILE"}}
    result = subprocess.run(
        ["git", "ls-files", *pathspecs],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return result.stdout.splitlines()


@cache
def tracked_source_files() -> frozenset[Path]:
    """Absolute paths to tracked `.py` files under `src/reporter`."""
    return frozenset(
        PROJECT_ROOT / line for line in _ls_files("src/reporter") if line.endswith(".py")
    )


@cache
def tracked_test_files() -> frozenset[Path]:
    """Absolute paths to tracked `.py` files under `tests`."""
    return frozenset(PROJECT_ROOT / line for line in _ls_files("tests") if line.endswith(".py"))


@cache
def tracked_prose_files() -> frozenset[Path]:
    """Absolute paths to every tracked `.md` file in the project.

    The whole project rather than `docs`, because `README.md` sits at the
    root and is the page a reader meets first.
    """
    return frozenset(PROJECT_ROOT / line for line in _ls_files() if line.endswith(".md"))


@cache
def tracked_file_basenames() -> frozenset[str]:
    """Every tracked file in the project, by basename alone.

    For the one check asking whether a path a docstring cites still
    exists. Basenames rather than paths because a citation is prose and
    may be written from any directory's point of view; what it has to
    answer is whether the reader has something to open.
    """
    return frozenset(line.rsplit("/", 1)[-1] for line in _ls_files() if line)
