# Workflow

*Commits, branches, and what a test has to be called.*

The chassis rules, and only the parts that bind a plain Python library. The
keeper carries the rest, because they are about bounded contexts, event
sourcing and a database this project does not have.

## Commits

Conventional Commits with scope: `type(scope): subject`. Imperative, lowercase, no trailing period, under 72 characters.

| Type | Use for |
| --- | --- |
| `feat` | New caller-visible capability |
| `fix` | Bug fix |
| `refactor` | Internal restructure, no behavior change |
| `perf` | Performance |
| `test` | Tests only |
| `docs` | Docs only |
| `build` | Build, deps, packaging |
| `ci` | CI, pre-commit, hooks |
| `chore` | Anything else not user-visible |

**Scopes:** `translate`, `session`, `relay`, `client`, `stores`, `sources`, `wire`, `config`. Repo-level ones are `repo`, `deps` and `ci`. Pick the dominant scope or omit it.

**Granularity:** one commit is one cohesive change that compiles and passes tests. Port, adapter, and test for one capability is one commit. Refactor plus feature is two.

The subject line says WHAT; the body says WHY.

## Branch flow

Solo: commit directly to `main`. CI must be green before pushing.

**For anything non-trivial, use a worktree.** `git worktree add ../reporter-<task> main`, work there, commit, and return. Two reasons:

- A parallel session's checkout can destroy uncommitted work in the main tree.
- Pre-commit stashes unstaged changes to tracked files but [never untracked ones](https://github.com/pre-commit/pre-commit/issues/1212). A half-staged work-in-progress slice (untracked `handler.py` plus unstaged `wire.py` edits hidden by the stash) will false-fail architecture fitness functions and force `--no-verify` to land an otherwise-clean commit.

Also avoid `git commit -- <paths>` with mixed staged and unstaged state: the path form bypasses the index in a way pre-commit's stash flow does not expect. Stage everything and verify `git diff` is empty before committing.

## Test names
Descriptive-sentence pytest style: snake_case prefixed with `test_`.

```
test_<subject>_<expected_outcome>[_<scenario>]
```

- **subject**: the unit under test.
- **expected_outcome**: the property pinned, not the inputs.
- **scenario** (optional): conditions, introduced with `when_` or `for_`.

Optimize for the property, not the inputs.

**Good:**

```
test_decide_emits_thing_defined_when_stream_is_empty
test_handler_returns_thing_for_known_id
test_post_things_returns_201_with_thing_id
```

**Avoid:**

```
test_post_things_with_three_parts_in_order_b_a_c   # describes inputs
test_handler_3                                      # opaque
test_register_thing_works                           # outcome too vague
```
