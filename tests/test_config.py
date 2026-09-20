"""Configuration is refused at load, not discovered at 3am.

Every check here is a failure a reporter would otherwise hit on the first
run of some plan, hours after starting, with a message pointing at AROC
rather than at the file that is wrong.
"""

import re
from pathlib import Path
from uuid import UUID

import pytest

from reporter.config import ConfigError, ReporterConfig, from_mapping, load

A_PLAN = "01a0ba64-8f95-7ad1-a7a7-44124ff3afd5"

WELL_FORMED = {
    "aroc": {
        "base_url": "https://aroc.example/",
        "token": "a-token",
        "external_ref_scheme": "engine-run-uid",
    },
    "plans": {"count": A_PLAN},
}


def test_a_well_formed_document_loads() -> None:
    config = from_mapping(WELL_FORMED)

    assert config.token == "a-token"
    assert config.external_ref_scheme == "engine-run-uid"
    assert config.plan_id_for("count") == UUID(A_PLAN)


def test_a_trailing_slash_on_the_base_url_is_dropped() -> None:
    """Otherwise every path this builds carries a double slash, which some
    servers route and some do not."""
    assert from_mapping(WELL_FORMED).base_url == "https://aroc.example"


def test_an_unknown_plan_name_resolves_to_nothing() -> None:
    """Not an error here, and a refusal upstream. A run whose plan this
    installation does not recognise must not be reported against a guess."""
    assert from_mapping(WELL_FORMED).plan_id_for("scan") is None


def test_an_empty_plan_map_is_allowed() -> None:
    """A reporter stood up before its plans are authored refuses every run,
    which is a legitimate state and a loud one."""
    document = {"aroc": dict(WELL_FORMED["aroc"]), "plans": {}}

    assert from_mapping(document).plan_ids == {}


def test_a_missing_plans_table_is_the_same_as_an_empty_one() -> None:
    assert from_mapping({"aroc": dict(WELL_FORMED["aroc"])}).plan_ids == {}


@pytest.mark.parametrize("key", ["base_url", "token", "external_ref_scheme"])
def test_a_missing_required_setting_is_refused_by_name(key: str) -> None:
    aroc = {k: v for k, v in WELL_FORMED["aroc"].items() if k != key}

    with pytest.raises(ConfigError, match=key):
        from_mapping({"aroc": aroc, "plans": {}})


@pytest.mark.parametrize("empty", ["", "   "])
def test_a_blank_required_setting_is_refused(empty: str) -> None:
    """A present-but-empty token is the shape an unset environment variable
    takes after substitution, and it authenticates as nobody."""
    aroc = {**WELL_FORMED["aroc"], "token": empty}

    with pytest.raises(ConfigError, match="token"):
        from_mapping({"aroc": aroc, "plans": {}})


def test_a_base_url_that_is_not_a_url_is_refused() -> None:
    aroc = {**WELL_FORMED["aroc"], "base_url": "aroc.example"}

    with pytest.raises(ConfigError, match="http"):
        from_mapping({"aroc": aroc, "plans": {}})


def test_a_plan_id_that_is_not_an_id_is_refused_and_names_the_plan() -> None:
    """The message has to name the plan, because a map with thirty entries
    and one typo is otherwise a search."""
    document = {"aroc": dict(WELL_FORMED["aroc"]), "plans": {"count": "not-an-id"}}

    with pytest.raises(ConfigError, match="count"):
        from_mapping(document)


def test_a_plan_id_that_is_not_a_string_is_refused() -> None:
    document = {"aroc": dict(WELL_FORMED["aroc"]), "plans": {"count": 7}}

    with pytest.raises(ConfigError, match="count"):
        from_mapping(document)


def test_a_file_is_read_and_parsed(tmp_path: Path) -> None:
    path = tmp_path / "reporter.toml"
    path.write_text(
        "[aroc]\n"
        'base_url = "https://aroc.example"\n'
        'token = "a-token"\n'
        'external_ref_scheme = "engine-run-uid"\n'
        "\n"
        "[plans]\n"
        f'count = "{A_PLAN}"\n',
        encoding="utf-8",
    )

    config = load(path)

    assert isinstance(config, ReporterConfig)
    assert config.plan_id_for("count") == UUID(A_PLAN)


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


# The store table, which is optional. Its absence switches the dataset leg
# off; its presence and being wrong is refused like anything else here.

WITH_STORE = {
    **WELL_FORMED,
    "store": {
        "base_url": "https://store.example/",
        "root": "/raw/",
        "external_ref_scheme": "tiled-node-path",
    },
}


def test_a_document_with_no_store_table_switches_the_dataset_leg_off() -> None:
    """A real deployment rather than a degraded one, so it is `None` and not
    an empty configuration that would look reachable."""
    assert from_mapping(WELL_FORMED).store is None


def test_a_store_table_loads_and_is_punctuated_once() -> None:
    store = from_mapping(WITH_STORE).store

    assert store is not None
    assert store.base_url == "https://store.example"
    assert store.root == "raw"
    assert store.external_ref_scheme == "tiled-node-path"


def test_a_store_serving_its_runs_from_the_top_level_may_leave_the_root_out() -> None:
    """An empty root is an arrangement, not an omission."""
    store = from_mapping({**WELL_FORMED, "store": {**WITH_STORE["store"], "root": ""}}).store

    assert store is not None
    assert store.root == ""


def test_a_store_with_no_root_at_all_is_read_as_the_top_level() -> None:
    table = {k: v for k, v in WITH_STORE["store"].items() if k != "root"}
    store = from_mapping({**WELL_FORMED, "store": table}).store

    assert store is not None
    assert store.root == ""


def test_the_two_reference_schemes_are_separate_settings() -> None:
    """One names the vocabulary an engine's run ids belong to and the other
    a store's addresses. A deployment that conflated them would be saying
    two kinds of reference are interchangeable."""
    config = from_mapping(WITH_STORE)

    assert config.store is not None
    assert config.external_ref_scheme != config.store.external_ref_scheme


@pytest.mark.parametrize("missing", ["base_url", "external_ref_scheme"])
def test_a_store_table_missing_a_required_field_is_refused_by_name(missing: str) -> None:
    table = {k: v for k, v in WITH_STORE["store"].items() if k != missing}

    with pytest.raises(ConfigError, match=re.escape(f"store.{missing}")):
        from_mapping({**WELL_FORMED, "store": table})


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
