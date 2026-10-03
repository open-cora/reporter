"""Everything this reporter has to be told, and nothing it can work out.

Two facts about the keeper, the vocabulary it files addresses in, and
an optional group about a store.

## Why nothing here maps a routine or a reference

The keeper composes the work, and the execution and step ids arrive in
the engine's own metadata, so this reporter resolves nothing and creates
nothing. There is no map from an engine's routine names onto the
keeper's operation ids, and nothing declaring the vocabulary an engine's
run ids belong to. An operator authoring a new routine has nothing to
add here, which is one fewer deployment fact to keep in step.

The engine's own run id still travels, as a step's `engine_reference`. It
is a plain string over there rather than a scheme-and-value pair, so
there is nothing to configure about it.

## Two tables, because filing and locating are two capabilities

`[dataset]` carries `external_ref_scheme`, the vocabulary the addresses
this reporter files belong to, and its presence switches filing on. It
also carries an optional `describer`, which switches on saying what is
inside the data as well as where it is. `[store]` carries a store's
`base_url` and `root`, and its presence switches locating on.

They were one table, on the reasoning that an address always comes from
a store, so a deployment changing where its data is kept changes both
together. That holds for an engine answering with a name, where
something else has to be asked where the run went. It does not hold for
an engine answering with a path: a TomoScan server reports the file it
wrote, so there is an address to file and nothing to resolve. Bundling
them meant describing a store that does not exist in order to file an
address already in hand, and the store probe then refused to start.

Each absence is a setting rather than a degraded state. No `[dataset]`
records runs and says nothing about data, without a lookup that always
answers nothing. No `[store]` files what the engine already said and
asks nobody.

A `[store]` with no `[dataset]` is the one pairing refused, because
locating an address this reporter has no vocabulary to file is a job it
could only half finish. `root` is where the writer points: a search does
not descend, so a reporter cannot discover its own scope, and a
misconfigured root finds nothing rather than finding the wrong thing.
"""

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast


class ConfigError(ValueError):
    """The configuration cannot be used, with the reason a person can fix.

    Raised at load rather than at first use. A reporter that starts with a
    malformed store table and discovers it on the first run of the day has
    turned a typo into an outage; one that refuses to start has turned it
    into a message.
    """


DESCRIBERS: Final[frozenset[str]] = frozenset({"dxchange-hdf5"})
"""What `dataset.describer` may name.

Names only. What each one builds lives at the entrypoint, because
building one means importing a format library and this module is read
before anything has decided whether that library is wanted. Keeping the
names here is what lets a typo be refused at load rather than on the
first scan that ends.

The two sides are checked against each other by a test, because a name
listed here that the entrypoint cannot build would pass configuration
and then describe nothing, which is the failure mode that is hardest to
see from either side alone.
"""


@dataclass(frozen=True)
class StoreConfig:
    """Which store holds the data, and where its runs are."""

    base_url: str
    root: str


@dataclass(frozen=True)
class ReporterConfig:
    """Where the keeper is, who this reporter is, and where the data is kept."""

    base_url: str
    token: str
    external_ref_scheme: str | None = None
    describer: str | None = None
    store: StoreConfig | None = None


def load(path: Path) -> ReporterConfig:
    """Read a configuration file, or say exactly what is wrong with it.

    TOML because the store settings are a table, which is clumsy in
    environment variables and obvious in a file, and because `tomllib` is
    in the standard library so reading one costs no dependency.

    Two required settings is few enough to argue for environment
    variables, and the tables are what keep a file worth having. A
    deployment that files what its engine reported and asks no store has
    a four-line file, which is not a burden.

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
    keeper: Mapping[str, Any] = settings.get("keeper") or {}
    base_url = _required_string(keeper, "base_url", source)
    token = _required_string(keeper, "token", source)

    if not base_url.startswith(("http://", "https://")):
        raise ConfigError(
            f"{source}: keeper.base_url must be an http or https URL, got {base_url!r}"
        )

    store = _store(settings.get("store"), source)
    scheme, describer = _dataset(settings.get("dataset"), source)
    if store is not None and scheme is None:
        raise ConfigError(
            f"{source}: there is a store table and no dataset table, so this reporter "
            "could find where a run went and have no vocabulary to file the address in. "
            "Add dataset.external_ref_scheme, or remove the store."
        )

    return ReporterConfig(
        base_url=base_url.rstrip("/"),
        token=token,
        external_ref_scheme=scheme,
        describer=describer,
        store=store,
    )


def _dataset(table: Any, source: str) -> tuple[str | None, str | None]:
    """Parse the dataset table, or say there is none.

    A missing table switches filing off, which is the deployment that
    records runs and says nothing about data. A table that is present
    and wrong is an error, for the reason the store table is: a typo
    found on the first run that ended is an outage, and one found at
    load is a message.

    `describer` is optional where the scheme is required, and the two
    are different kinds of fact. A deployment that files has to say
    what vocabulary its addresses are in, because the address is
    meaningless without it. A deployment that files does not have to
    be able to read its own data, and most cannot: there is an adapter
    for one format so far.

    A name nothing answers to is an error rather than a shrug. The
    alternative is a reporter that runs for a month looking configured
    and recording nothing about any of it, which is the shape of
    failure this whole file exists to turn into a message at load.
    """
    if table is None:
        return None, None
    if not isinstance(table, Mapping):
        raise ConfigError(f"{source}: dataset must be a table, or left out entirely")

    known: Mapping[str, Any] = cast("Mapping[str, Any]", table)
    scheme = _required_string(known, "external_ref_scheme", source, table_name="dataset")
    describer = known.get("describer")
    if describer is None:
        return scheme, None
    if not isinstance(describer, str) or not describer.strip():
        raise ConfigError(f"{source}: dataset.describer must be a non-empty string")
    if describer not in DESCRIBERS:
        known_names = ", ".join(sorted(DESCRIBERS))
        raise ConfigError(
            f"{source}: dataset.describer is {describer!r}, which nothing here answers to. "
            f"Use one of: {known_names}. Leave it out to file addresses and say "
            "nothing about what is in the data."
        )
    return scheme, describer


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

    return StoreConfig(base_url=base_url.rstrip("/"), root=root.strip("/"))


def _required_string(
    table: Mapping[str, Any], key: str, source: str, *, table_name: str = "keeper"
) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(
            f"{source}: {table_name}.{key} is required and must be a non-empty string"
        )
    return value.strip()


__all__ = ["ConfigError", "ReporterConfig", "StoreConfig", "from_mapping", "load"]
