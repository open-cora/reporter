.PHONY: install lint fmt typecheck test docs-serve docs-build \
        refresh-captures precommit precommit-run clean help

# One project, one lockfile, one virtualenv. Every target runs here rather
# than looping over a tree, which is the difference between this Makefile and
# the one it was split out of.
STYLED := src tests typings

help:
	@echo "Common targets:"
	@echo "  install         Install Python deps via uv"
	@echo "  lint            Run ruff check + format check"
	@echo "  fmt             Run ruff format and auto-fix"
	@echo "  typecheck       Run pyright, strict"
	@echo "  test            Run the suite"
	@echo "  refresh-captures Re-record the fixtures from a real engine and store"
	@echo "  docs-serve      Serve the docs site at http://127.0.0.1:8023"
	@echo "  docs-build      Build the docs site, strict"
	@echo "  precommit       Install pre-commit hooks (one-time per clone)"
	@echo "  precommit-run   Run all pre-commit hooks against all files"
	@echo "  clean           Remove caches and build artefacts"

install:
	uv sync

lint:
	uv run ruff check $(STYLED)
	uv run ruff format --check $(STYLED)

fmt:
	uv run ruff check --fix $(STYLED)
	uv run ruff format $(STYLED)

typecheck:
	uv run pyright src tests

test:
	uv run pytest

precommit:
	uv run pre-commit install
	uv run pre-commit install --hook-type pre-push

precommit-run:
	uv run pre-commit run --all-files

clean:
	rm -rf .pytest_cache .ruff_cache .pyright_cache build dist *.egg-info site
	find . -type d -name __pycache__ -exec rm -rf {} +

# The docs toolchain is not a project dependency: it is pulled per-invocation
# with `uv run --with`, pinned here so two machines render the same site.
MKDOCS := uv run --with mkdocs-material==9.7.7 mkdocs

docs-serve:
	$(MKDOCS) serve -a 127.0.0.1:8023

# `--strict` is what makes a broken cross-link fail rather than warn.
docs-build:
	$(MKDOCS) build --strict

# Re-record what a real engine and a real store actually do, into the two
# fixtures this suite asserts against.
#
# Deliberately unpinned. Installing the versions the findings were written
# against would make this incapable of discovering anything: same input,
# same output, green forever. Latest is the point.
#
# Do NOT commit the result on a whim. Ids and timestamps change every run,
# so the diff is almost all noise and a habit of committing it teaches
# everyone to ignore capture diffs. What to read is whether the suite still
# passes afterwards: the assertions are written against the structural
# claims, so a red test names the finding that moved. Commit the new capture
# only as part of reacting to one.
#
# Neither collector can run under a project. Both import an engine, and the
# store's client picks up a different httpx from the one this project locks.
# That is why these are two long invocations rather than a lane, and why the
# scripts sit outside the lint and typecheck scope.
refresh-captures:
	uv run --no-project --python 3.13 \
	    --with bluesky --with ophyd \
	    python scripts/collect_documents.py
	uv run --no-project --python 3.13 \
	    --with 'tiled[server,client]' --with bluesky --with ophyd \
	    python scripts/collect_nodes.py
	@echo
	@echo "Captures refreshed. Now run: make test"
	@echo "A red test names the finding that moved; the diff is mostly noise."
