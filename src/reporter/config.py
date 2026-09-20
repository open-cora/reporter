"""Everything this reporter has to be told, and nothing it can work out.

Four facts about AROC, an optional fifth group about a store, and the
interesting one is `plan_ids`.

AROC identifies a plan by id. An engine's documents carry only a name, and
two AROC plans may legitimately answer to one name, so turning a name into
an id is a choice somebody has to make. It is made here rather than by
asking AROC, because the answer depends on which installation this
reporter serves and AROC does not know that. Nothing on the two records
would tell it apart if it tried.

So the map is a deployment fact, written down where the deployment is. The
cost is real and worth stating: an operator who defines a new plan must
also add it here, and until they do, runs of it are refused. That failure
is loud, which is the trade against the alternative, where AROC guesses by
recency and records runs against whichever plan it happened to pick.

## The store table, and why its absence is a setting

`[store]` is optional and leaving it out switches the dataset leg off
entirely. That is a real state rather than a degraded one: a deployment
whose engine writes nowhere this reporter can see should record runs and
say nothing about data, and it should do that without a store lookup that
always answers nothing. `StoreConfig` is `None` in that case, and the
difference between "not configured" and "configured and empty" stays
visible.

Its `root` is where the writer points. A search does not descend, so a
reporter cannot discover its own scope, and a misconfigured root finds
nothing rather than finding the wrong thing.

Its `external_ref_scheme` is a second one and not the one above. That one
names the vocabulary an engine's run ids belong to, this one names the
vocabulary a store's addresses belong to, and a deployment that set them
to the same string would be saying two different kinds of reference are
interchangeable.
"""

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from uuid import UUID


class ConfigError(ValueError):
    """The configuration cannot be used, with the reason a person can fix.

    Raised at load rather than at first use. A reporter that starts with a
    malformed plan map and discovers it on the first run of the day has
    turned a typo into an outage; one that refuses to start has turned it
    into a message.
    """


@dataclass(frozen=True)
class StoreConfig:
    """Which store holds the data, where its runs are, and what to call them."""

    base_url: str
    root: str
    external_ref_scheme: str


@dataclass(frozen=True)
class ReporterConfig:
    """Where AROC is, who this reporter is, and what its plan names mean."""

    base_url: str
    token: str
    plan_ids: Mapping[str, UUID]
    external_ref_scheme: str
    store: StoreConfig | None = None

    def plan_id_for(self, plan_name: str) -> UUID | None:
        """The plan this installation means by that name, if it has one.

        `None` is not an error here and is a refusal upstream: a run whose
        plan this reporter does not recognise must not be reported against
        a guess. An adapter cannot honestly author a plan either, which is
        why there is no fallback that creates one.
        """
        return self.plan_ids.get(plan_name)


def load(path: Path) -> ReporterConfig:
    """Read a configuration file, or say exactly what is wrong with it.

    TOML because the plan map is a table of strings to ids, which is
    miserable in environment variables and obvious in a file, and because
    `tomllib` is in the standard library so reading one costs no
    dependency.

    The token is read from the file like everything else. A deployment
    that would rather inject it another way substitutes its own loader;
    this one is not the place to grow a second source of truth.
    """
    try:
        document: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"Cannot read {path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} is not valid TOML: {exc}") from exc

    return from_mapping(document, source=str(path))


def from_mapping(document: Mapping[str, Any], *, source: str = "configuration") -> ReporterConfig:
    """Build a configuration from an already-parsed document.

    Separate from `load` so the shape can be checked without a file, and
    so a deployment holding its settings somewhere else has one function
    to call rather than a format to imitate.
    """
    aroc: Mapping[str, Any] = document.get("aroc") or {}
    base_url = _required_string(aroc, "base_url", source)
    token = _required_string(aroc, "token", source)
    scheme = _required_string(aroc, "external_ref_scheme", source)

    if not base_url.startswith(("http://", "https://")):
        raise ConfigError(f"{source}: aroc.base_url must be an http or https URL, got {base_url!r}")

    return ReporterConfig(
        base_url=base_url.rstrip("/"),
        token=token,
        plan_ids=_plan_ids(document.get("plans") or {}, source),
        external_ref_scheme=scheme,
        store=_store(document.get("store"), source),
    )


def _store(table: Any, source: str) -> StoreConfig | None:
    """Parse the store table, or say there is none.

    A missing table is not an error and switches the dataset leg off. A
    table that is present and wrong is an error, for the same reason a
    malformed plan id is: it would otherwise fail on the first run that
    ended, at whatever hour that is.

    `root` is the one field allowed to be empty, because a store serving
    its runs from the top level is a legitimate arrangement and an empty
    string is how that is spelled.
    """
    if table is None:
        return None
    if not isinstance(table, Mapping):
        raise ConfigError(f"{source}: store must be a table, or left out entirely")

    known: Mapping[str, Any] = cast("Mapping[str, Any]", table)
    base_url = _required_string(known, "base_url", source, table_name="store")
    if not base_url.startswith(("http://", "https://")):
        raise ConfigError(
            f"{source}: store.base_url must be an http or https URL, got {base_url!r}"
        )

    root = known.get("root", "")
    if not isinstance(root, str):
        raise ConfigError(f"{source}: store.root must be a string, and may be empty")

    return StoreConfig(
        base_url=base_url.rstrip("/"),
        root=root.strip("/"),
        external_ref_scheme=_required_string(
            known, "external_ref_scheme", source, table_name="store"
        ),
    )


def _required_string(
    table: Mapping[str, Any], key: str, source: str, *, table_name: str = "aroc"
) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(
            f"{source}: {table_name}.{key} is required and must be a non-empty string"
        )
    return value.strip()


def _plan_ids(table: Mapping[str, Any], source: str) -> dict[str, UUID]:
    """Parse the name-to-id map, refusing anything that is not an id.

    An empty map is allowed and means every run is refused, which is a
    legitimate state for a reporter being stood up before its plans are
    authored. A malformed id is not: it would fail on the first run of
    that plan and nowhere earlier.
    """
    plan_ids: dict[str, UUID] = {}
    for name, value in table.items():
        if not isinstance(value, str):
            raise ConfigError(f"{source}: plans.{name} must be a plan id as a string")
        try:
            plan_ids[str(name)] = UUID(value)
        except ValueError as exc:
            raise ConfigError(f"{source}: plans.{name} is not a valid id: {value!r}") from exc
    return plan_ids


__all__ = ["ConfigError", "ReporterConfig", "StoreConfig", "from_mapping", "load"]
