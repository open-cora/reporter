"""The store side, against what a real store actually returned.

`nodes.json` is captured output: a real engine driven into a real store
through the writer a deployment would use, then interrogated from the
outside the way this reporter has to. The spike that captured it printed a
table and read it. Here the same facts are assertions, so a store release
that changes one fails a run instead of changing a report nobody re-reads.

Two of those facts are load-bearing and are checked directly rather than
taken on trust. One node reports two spellings of its address, which is
why `node_path` exists. And the address read off the raw HTTP surface is
the same one the store's own client reports, which is why this package
takes no store dependency.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from reporter.stores import (
    HttpStoreLookup,
    Location,
    StoreRefusedError,
    node_path,
    store_instant,
)

CAPTURED = Path(__file__).parent / "nodes.json"

BASE_URL = "http://store.example"
WRITER_ROOT = "raw"


def captured() -> dict[str, Any]:
    return json.loads(CAPTURED.read_text(encoding="utf-8"))


def scenarios() -> dict[str, dict[str, Any]]:
    return captured()["scenarios"]


class Answer:
    """One canned HTTP response, shaped like the part the adapter reads."""

    def __init__(self, status_code: int, payload: Any = None, text: str = "") -> None:
        self.status_code = status_code
        self.text = text
        self._payload = payload

    def json(self) -> Any:
        return self._payload


class Recorder:
    """Answers with what it was given, and remembers what it was asked."""

    def __init__(self, answer: Answer) -> None:
        self.answer = answer
        self.urls: list[str] = []

    def get(self, url: str) -> Answer:
        self.urls.append(url)
        return self.answer


def body_for(node: dict[str, Any], *, stop_time: float | None) -> dict[str, Any]:
    """The store's envelope, rebuilt around a captured node.

    The shape is the one the capture recorded: `data.attributes`, with
    `ancestors` and `metadata` on it. Rebuilding rather than replaying the
    whole response keeps a test that wants one field changed from having
    to carry a whole document to change it in.
    """
    metadata: dict[str, Any] = {"start": {"uid": node["key"]}}
    if stop_time is not None:
        metadata["stop"] = {"time": stop_time, "exit_status": "success"}
    return {
        "data": {
            "id": node["key"],
            "attributes": {"ancestors": node["ancestors"], "metadata": metadata},
        }
    }


def test_node_path_drops_the_empty_segment_that_makes_one_node_two_records() -> None:
    addressing = captured()["root_addressing"]
    for where, observed in addressing.items():
        created, searched = observed["created"], observed["searched"]
        assert observed["spellings"] == 2, f"{where} no longer splits, so the capture is stale"
        assert node_path(created["ancestors"], created["key"]) == node_path(
            searched["ancestors"], searched["key"]
        )


def test_node_path_agrees_with_every_address_the_store_reported() -> None:
    for label, scenario in scenarios().items():
        node = scenario["node"]
        assert node_path(node["ancestors"], node["key"]) == node["normalised_path"], label


def test_node_path_of_a_captured_run_fits_the_bound_aroc_puts_on_a_reference() -> None:
    identifier_value_max_length = 200
    for label, scenario in scenarios().items():
        node = scenario["node"]
        value = node_path(node["ancestors"], node["key"])
        assert 0 < len(value) <= identifier_value_max_length, label


def test_node_path_joins_without_a_leading_or_doubled_separator() -> None:
    assert node_path(["", "raw"], "abc") == "raw/abc"
    assert node_path(["raw", ""], "abc") == "raw/abc"
    assert node_path([], "abc") == "abc"
    assert node_path(["raw"], "") == "raw"


def test_the_address_read_over_http_is_the_one_the_stores_own_client_reported() -> None:
    """The finding that keeps the store's library out of this lockfile."""
    for label, scenario in scenarios().items():
        wire = scenario["over_http"]
        assert wire["same_key_as_the_client"] is True, label
        assert node_path(wire["ancestors"], wire["id"]) == scenario["node"]["normalised_path"]


def test_a_run_the_store_does_not_hold_answered_404_in_the_capture() -> None:
    not_found = 404
    for label, scenario in scenarios().items():
        assert scenario["over_http"]["missing_status"] == not_found, label


def test_locate_asks_the_metadata_route_under_the_configured_writer_root() -> None:
    scenario = scenarios()["completes"]
    node = scenario["node"]
    http = Recorder(Answer(200, body_for(node, stop_time=None)))

    HttpStoreLookup(http, BASE_URL, WRITER_ROOT).locate(node["key"])

    assert http.urls == [f"{BASE_URL}/api/v1/metadata/{WRITER_ROOT}/{node['key']}"]


def test_locate_builds_one_url_however_the_root_and_base_are_punctuated() -> None:
    node = scenarios()["completes"]["node"]
    http = Recorder(Answer(200, body_for(node, stop_time=None)))

    HttpStoreLookup(http, f"{BASE_URL}/", f"/{WRITER_ROOT}/").locate(node["key"])

    assert http.urls == [f"{BASE_URL}/api/v1/metadata/{WRITER_ROOT}/{node['key']}"]


def test_locate_reports_a_store_serving_from_its_root_without_a_doubled_separator() -> None:
    node = scenarios()["completes"]["node"]
    http = Recorder(Answer(200, body_for(node, stop_time=None)))

    HttpStoreLookup(http, BASE_URL, "").locate(node["key"])

    assert http.urls == [f"{BASE_URL}/api/v1/metadata/{node['key']}"]


def test_locate_returns_the_address_and_the_ending_the_store_holds() -> None:
    scenario = scenarios()["completes"]
    node = scenario["node"]
    stop_time = scenario["store_stop_time"]
    http = Recorder(Answer(200, body_for(node, stop_time=stop_time)))

    located = HttpStoreLookup(http, BASE_URL, WRITER_ROOT).locate(node["key"])

    assert located == Location(
        path=node["normalised_path"],
        occurred_at=datetime.fromtimestamp(stop_time, tz=UTC),
    )


def test_locate_returns_the_engines_own_ending_time_to_the_last_digit() -> None:
    """The store keeps the engine's timestamps verbatim, so a record can use them."""
    for label, scenario in scenarios().items():
        node = scenario["node"]
        http = Recorder(Answer(200, body_for(node, stop_time=scenario["store_stop_time"])))

        located = HttpStoreLookup(http, BASE_URL, WRITER_ROOT).locate(node["key"])

        assert located is not None
        assert located.occurred_at is not None
        assert located.occurred_at.timestamp() == scenario["engine_stop_time"], label


def test_locate_returns_a_location_with_no_time_when_the_store_holds_no_ending() -> None:
    """A node without its ending is a reporter that got there before the writer."""
    node = scenarios()["completes"]["node"]
    http = Recorder(Answer(200, body_for(node, stop_time=None)))

    located = HttpStoreLookup(http, BASE_URL, WRITER_ROOT).locate(node["key"])

    assert located == Location(path=node["normalised_path"], occurred_at=None)


def test_locate_returns_nothing_for_a_run_the_store_does_not_hold() -> None:
    http = Recorder(Answer(404, text="not found"))

    assert HttpStoreLookup(http, BASE_URL, WRITER_ROOT).locate("no-such-run") is None


@pytest.mark.parametrize("status", [401, 403, 500, 503])
def test_locate_refuses_loudly_on_any_answer_that_is_not_a_node_or_a_404(status: int) -> None:
    http = Recorder(Answer(status, text="nope"))

    with pytest.raises(StoreRefusedError) as refusal:
        HttpStoreLookup(http, BASE_URL, WRITER_ROOT).locate("a-run")

    assert refusal.value.status == status


def test_store_instant_reads_a_unix_time_as_an_aware_moment() -> None:
    assert store_instant(1789915675.86416) == datetime.fromtimestamp(1789915675.86416, tz=UTC)


@pytest.mark.parametrize("unusable", [None, "1789915675", True, {}, []])
def test_store_instant_declines_anything_that_is_not_a_number(unusable: Any) -> None:
    assert store_instant(unusable) is None
