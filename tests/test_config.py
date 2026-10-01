"""Configuration is refused at load, not discovered at 3am.

Every check here is a failure a reporter would otherwise hit on the first
scan of the day, hours after starting, with a message pointing at the keeper
rather than at the file that is wrong.

There is much less to get wrong than there was. The plan map and the
engine's reference scheme are gone, because the keeper dispatches the work and
the ids arrive with the delivery, so what remains is where the keeper is, who
this reporter is, and an optional store.
"""

import re
from pathlib import Path

import pytest

from reporter.config import ConfigError, ReporterConfig, from_mapping, load

WELL_FORMED = {
    "keeper": {
        "base_url": "https://keeper.example/",
        "token": "a-token",
    },
}


def test_a_well_formed_mapping_loads() -> None:
    config = from_mapping(WELL_FORMED)

    assert config.token == "a-token"
    assert config.base_url == "https://keeper.example"


def test_a_trailing_slash_on_the_base_url_is_dropped() -> None:
    """Otherwise every path this builds carries a double slash, which some
    servers route and some do not."""
    assert from_mapping(WELL_FORMED).base_url == "https://keeper.example"


def test_a_table_this_file_no_longer_knows_about_is_ignored() -> None:
    """An operator upgrading has a file with a plan map still in it.

    Refusing it would turn an upgrade into an outage over a setting
    nothing reads. Ignoring it is the reversible direction: the map does
    nothing, and a later version may want the key back.
    """
    settings = {**WELL_FORMED, "plans": {"count": "01a0ba64-8f95-7ad1-a7a7-44124ff3afd5"}}

    assert from_mapping(settings).base_url == "https://keeper.example"


@pytest.mark.parametrize("key", ["base_url", "token"])
def test_a_missing_required_setting_is_refused_by_name(key: str) -> None:
    keeper = {k: v for k, v in WELL_FORMED["keeper"].items() if k != key}

    with pytest.raises(ConfigError, match=key):
        from_mapping({"keeper": keeper})


@pytest.mark.parametrize("empty", ["", "   "])
def test_a_blank_required_setting_is_refused(empty: str) -> None:
    """A present-but-empty token is the shape an unset environment variable
    takes after substitution, and it authenticates as nobody."""
    keeper = {**WELL_FORMED["keeper"], "token": empty}

    with pytest.raises(ConfigError, match="token"):
        from_mapping({"keeper": keeper})


def test_a_base_url_that_is_not_a_url_is_refused() -> None:
    keeper = {**WELL_FORMED["keeper"], "base_url": "keeper.example"}

    with pytest.raises(ConfigError, match="http"):
        from_mapping({"keeper": keeper})


def test_a_file_is_read_and_parsed(tmp_path: Path) -> None:
    path = tmp_path / "reporter.toml"
    path.write_text(
        '[keeper]\nbase_url = "https://keeper.example"\ntoken = "a-token"\n',
        encoding="utf-8",
    )

    config = load(path)

    assert isinstance(config, ReporterConfig)
    assert config.base_url == "https://keeper.example"


def test_a_missing_file_says_which_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=re.escape("reporter.toml")):
        load(tmp_path / "reporter.toml")


def test_a_file_that_is_not_toml_says_so(tmp_path: Path) -> None:
    """Distinct from a missing file and from a valid file with a bad value,
    because the three have different fixes."""
    path = tmp_path / "reporter.toml"
    path.write_text("this is not toml {{{", encoding="utf-8")

    with pytest.raises(ConfigError, match="valid TOML"):
        load(path)


# Two optional tables. `[dataset]` switches filing on, `[store]` switches
# locating on, and either being present and wrong is refused like anything
# else here. A store with no dataset is the one pairing refused outright.

WITH_SCHEME = {**WELL_FORMED, "dataset": {"external_ref_scheme": "tiled-node-path"}}

WITH_STORE = {
    **WITH_SCHEME,
    "store": {
        "base_url": "https://store.example/",
        "root": "/raw/",
    },
}


def test_a_mapping_with_no_store_table_switches_the_dataset_leg_off() -> None:
    """A real deployment rather than a degraded one, so it is `None` and not
    an empty configuration that would look reachable."""
    assert from_mapping(WELL_FORMED).store is None


def test_a_store_table_loads_and_is_punctuated_once() -> None:
    store = from_mapping(WITH_STORE).store

    assert store is not None
    assert store.base_url == "https://store.example"
    assert store.root == "raw"


def test_a_store_serving_its_runs_from_the_top_level_may_leave_the_root_out() -> None:
    """An empty root is an arrangement, not an omission."""
    store = from_mapping({**WITH_SCHEME, "store": {**WITH_STORE["store"], "root": ""}}).store

    assert store is not None
    assert store.root == ""


def test_a_store_with_no_root_at_all_is_read_as_the_top_level() -> None:
    table = {k: v for k, v in WITH_STORE["store"].items() if k != "root"}
    store = from_mapping({**WITH_SCHEME, "store": table}).store

    assert store is not None
    assert store.root == ""


def test_the_one_scheme_left_belongs_to_the_reporter_rather_than_to_the_store() -> None:
    """It sat on the store table while every address came from a store.

    An engine that answers with a path supplies the address itself, so
    the vocabulary is the reporter's to declare and the store is a
    separate question. An engine's own run id still travels as a step's
    `engine_reference`, a plain string over there rather than a
    scheme-and-value pair, so there is still nothing to configure there.
    """
    config = from_mapping(WITH_STORE)

    assert config.external_ref_scheme == "tiled-node-path"
    assert config.store is not None
    assert not hasattr(config.store, "external_ref_scheme")


def test_a_scheme_with_no_store_files_what_the_engine_reported_and_asks_nobody() -> None:
    """The deployment the split exists for.

    A TomoScan server names the file it wrote, so there is an address to
    file and nothing to resolve. Before the split this could not be
    configured at all: asking to file meant describing a store that does
    not exist, and the startup probe then refused to run.
    """
    config = from_mapping(WITH_SCHEME)

    assert config.external_ref_scheme == "tiled-node-path"
    assert config.store is None


def test_a_store_with_no_scheme_is_refused_rather_than_half_built() -> None:
    """Locating an address it could not then file is a job half finished."""
    with pytest.raises(ConfigError, match=re.escape("dataset.external_ref_scheme")):
        from_mapping({**WELL_FORMED, "store": WITH_STORE["store"]})


def test_a_dataset_table_missing_the_scheme_is_refused_by_name() -> None:
    with pytest.raises(ConfigError, match=re.escape("dataset.external_ref_scheme")):
        from_mapping({**WELL_FORMED, "dataset": {}})


def test_a_dataset_that_is_not_a_table_is_refused_rather_than_ignored() -> None:
    """The twin of the store case, and the same silent failure if ignored."""
    with pytest.raises(ConfigError, match="dataset must be a table"):
        from_mapping({**WELL_FORMED, "dataset": "posix-file"})


def test_a_store_table_missing_its_base_url_is_refused_by_name() -> None:
    table = {k: v for k, v in WITH_STORE["store"].items() if k != "base_url"}

    with pytest.raises(ConfigError, match=re.escape("store.base_url")):
        from_mapping({**WITH_SCHEME, "store": table})


def test_a_store_base_url_that_is_not_a_url_is_refused() -> None:
    with pytest.raises(ConfigError, match=re.escape("store.base_url")):
        from_mapping({**WELL_FORMED, "store": {**WITH_STORE["store"], "base_url": "store.example"}})


def test_a_store_root_that_is_not_a_string_is_refused() -> None:
    with pytest.raises(ConfigError, match=re.escape("store.root")):
        from_mapping({**WELL_FORMED, "store": {**WITH_STORE["store"], "root": 7}})


def test_a_store_that_is_not_a_table_is_refused_rather_than_ignored() -> None:
    """Left out is a setting. Present and nonsense is a typo, and a typo
    that switched the leg off silently is the failure this exists to stop."""
    with pytest.raises(ConfigError, match="store must be a table"):
        from_mapping({**WELL_FORMED, "store": "https://store.example"})
