"""Everything this reporter has to be told, and nothing it can work out.

Two facts about AROC, and an optional group about a store.

## What used to be here, and why it is not

Two settings are gone, and both for one reason. `plan_ids` mapped an
engine's plan names onto AROC plan ids, because a run was a record this
reporter brought into existence and the id was not derivable from
anything on a document. `external_ref_scheme` named the vocabulary an
engine's run ids belonged to, because that reference was stored on the
run and later used to find it again.

AROC composes the work now. The execution and step ids arrive in the
engine's own metadata, so nothing is resolved, nothing is created, and
the deployment fact those two settings carried is not a fact this
reporter needs. An operator authoring a new plan no longer has to
remember to add it here, which removes the one failure mode this file
previously argued was worth its cost.

The engine's own run id still travels, as a step's `engine_reference`. It
is a plain string over there rather than a scheme-and-value pair, so
there is nothing to configure about it.

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

Its `external_ref_scheme` is the one scheme left. It names the vocabulary
a store's addresses belong to, and it is on the store table rather than
beside the AROC settings because it describes the store: a deployment
that changes where its data is kept changes both together.
"""

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast


class ConfigError(ValueError):
    """The configuration cannot be used, with the reason a person can fix.

    Raised at load rather than at first use. A reporter that starts with a
    malformed store table and discovers it on the first run of the day has
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
    """Where AROC is, who this reporter is, and where the data is kept."""

    base_url: str
    token: str
    store: StoreConfig | None = None


def load(path: Path) -> ReporterConfig:
    """Read a configuration file, or say exactly what is wrong with it.

    TOML because the store settings are a table, which is clumsy in
    environment variables and obvious in a file, and because `tomllib` is
    in the standard library so reading one costs no dependency.

    Two required settings is few enough to argue for environment
    variables, and the store table is what keeps a file worth having. A
    deployment that runs without a store has a two-line file, which is
    not a burden.

    The token is read from the file like everything else. A deployment
    that would rather inject it another way substitutes its own loader;
    this one is not the place to grow a second source of truth.
    """
    try:
        settings: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"Cannot read {path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} is not valid TOML: {exc}") from exc

    return from_mapping(settings, source=str(path))


def from_mapping(settings: Mapping[str, Any], *, source: str = "configuration") -> ReporterConfig:
    """Build a configuration from an already-parsed mapping.

    Separate from `load` so the shape can be checked without a file, and
    so a deployment holding its settings somewhere else has one function
    to call rather than a format to imitate.
    """
    keeper: Mapping[str, Any] = settings.get("aroc") or {}
    base_url = _required_string(keeper, "base_url", source)
    token = _required_string(keeper, "token", source)

    if not base_url.startswith(("http://", "https://")):
        raise ConfigError(f"{source}: aroc.base_url must be an http or https URL, got {base_url!r}")

    return ReporterConfig(
        base_url=base_url.rstrip("/"),
        token=token,
        store=_store(settings.get("store"), source),
    )


def _store(table: Any, source: str) -> StoreConfig | None:
    """Parse the store table, or say there is none.

    A missing table is not an error and switches the dataset leg off. A
    table that is present and wrong is an error, because it would
    otherwise fail on the first run that ended, at whatever hour that is.

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


__all__ = ["ConfigError", "ReporterConfig", "StoreConfig", "from_mapping", "load"]
