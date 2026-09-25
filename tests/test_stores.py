"""The store side, against what a real store actually returned.

`nodes.json` is captured output: a real engine driven into a real store
through the writer a deployment would use, then interrogated from the
outside the way this reporter has to. The spike that captured it printed a
table and read it. Here the same facts are assertions, so a store release
that changes one fails a run instead of changing a report nobody re-reads.

## Two kinds of test, and the second kind runs nothing

Most of this file drives `HttpStoreLookup` over a transport shaped like
the captured response. The block at the foot drives nothing at all: it
reads the capture and asserts claims about the store that something here
was built on, so that re-running the collector against a newer store
turns a changed claim into a red test naming it rather than into a diff
nobody reads.

That second kind is the whole reason the collector is not deleted. A
capture nobody asserts against is a file; a capture with these on it is
the closest this suite gets to testing the real thing, at the cost of
somebody remembering to refresh it.

Four of the claims below back a decision that shipped: the writer is
subscribed first because ordering is deterministic, `[store] root` is
required because a search does not descend, an empty node is registered
anyway because every ending produces one, and the asset URI was dropped
as a key because the writer's readings have no file.
"""

import json
from datetime import UTC, datetime, timedelta
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


def test_locate_returns_the_engines_own_ending_moment_to_the_microsecond() -> None:
    """As close to the engine's own ending as a datetime can carry.

    Not to the last digit, which is what this asserted until a refreshed
    capture produced `...8619268` and the round trip returned `...861927`.
    The loss is real and is this conversion's, not the store's: an engine
    stamps a float with sub-microsecond precision and `datetime` holds
    microseconds. Two hundred nanoseconds is far below anything a record
    of when data was written could mean.

    That the store keeps the engine's number exactly is a separate claim
    and is checked against the capture further down, float to float, where
    it is true without a caveat.
    """
    tolerance = timedelta(microseconds=1)
    for label, scenario in scenarios().items():
        node = scenario["node"]
        http = Recorder(Answer(200, body_for(node, stop_time=scenario["store_stop_time"])))

        located = HttpStoreLookup(http, BASE_URL, WRITER_ROOT).locate(node["key"])

        assert located is not None
        assert located.occurred_at is not None
        engine = datetime.fromtimestamp(scenario["engine_stop_time"], tz=UTC)
        assert abs(located.occurred_at - engine) < tolerance, label


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


# Findings that back a shipped decision, read straight out of the capture.
#
# Nothing below exercises this package. Each one asserts a claim about the
# store that something here was built on, so that re-running the collector
# against a newer store turns a changed claim into a red test naming it
# rather than into a diff nobody reads. A spike
# is where each came from; the section is on the test.


def test_a_reporter_subscribed_after_the_writer_sees_a_finished_node() -> None:
    """Section 2, and the reason the README says to order them that way.

    If callback ordering ever stops being deterministic, a reporter goes
    back to needing a retry loop and every dataset lands with no
    timestamp, which nothing downstream would report as wrong.
    """
    observed = captured()["subscription_order"]["writer first"]
    at_stop = next(s for s in observed["sightings"] if s["at"] == "stop")

    assert at_stop["present"] is True
    assert at_stop["has_stop"] is True, (
        "A reporter subscribed after the writer no longer sees a finished node at stop, "
        "so the README's ordering instruction is wrong and the leg needs a retry."
    )


def test_a_reporter_subscribed_before_the_writer_sees_an_unfinished_one() -> None:
    """The other half of section 2, which is what makes it an ordering fact
    rather than a race: both directions are deterministic."""
    observed = captured()["subscription_order"]["reporter first"]
    at_start, at_stop = observed["sightings"]

    assert at_start["present"] is False
    assert at_stop["present"] is True
    assert at_stop["has_stop"] is False


def test_a_search_does_not_reach_a_run_from_the_top_of_the_store() -> None:
    """Section 5, and the reason `[store] root` is required configuration.

    A store that started descending would make that field optional, which
    is a simplification worth knowing about.
    """
    for label, scenario in scenarios().items():
        found = scenario["search"]
        assert found["from_the_store_root"] == [], (
            f"{label}: a search from the store root now finds runs, so `root` may no "
            "longer need to be configured."
        )
        assert found["from_the_writer_root"] == [scenario["run_uid"]], label


def test_every_ending_produced_a_node_and_most_of_them_hold_nothing() -> None:
    """Section 6, and the reason the reporter registers an empty node.

    Three of four captured runs ended before a reading was taken. If a
    failed run stopped producing a node at all, "register it anyway"
    becomes a rule about something that is not there.
    """
    empty = 0
    for label, scenario in scenarios().items():
        assert scenario["keys_under_the_writer_root"] == [scenario["run_uid"]], label
        if not [row for row in scenario["tree"] if row["depth"] == 1]:
            empty += 1

    assert empty, "No captured run ended empty, so the case the rule exists for is gone."


def test_the_writers_readings_have_no_file_a_record_could_point_at() -> None:
    """Section 4, and the reason the third candidate key was dropped.

    A run's readings are rows in a table. An array written directly is a
    file and says so, which is what makes this a fact about the writer
    rather than about the store.
    """
    bytes_are = captured()["where_the_bytes_are"]

    assert all(row["data_sources"] is None for row in bytes_are["by_the_writer"]), (
        "The writer's nodes now carry data_sources, so there is a file to point at and "
        "the asset URI is a candidate key again."
    )
    assert bytes_are["by_the_client"]["assets"], (
        "A directly written array no longer reports a file, so the contrast this rests on "
        "is gone and the finding says less than it claims."
    )


def test_the_store_keeps_every_timestamp_and_status_the_engine_emitted() -> None:
    """Section 3, float to float, which is where the claim is exact.

    The adapter test above can only check this to a microsecond, because
    that is all a `datetime` holds. Here there is no conversion in the
    way, so "verbatim" is asserted as written: three fields, four runs,
    and nothing else in the suite reads two of them.
    """
    for label, scenario in scenarios().items():
        assert scenario["store_start_time"] == scenario["engine_start_time"], label
        assert scenario["store_stop_time"] == scenario["engine_stop_time"], label
        assert scenario["store_exit_status"] == scenario["engine_exit_status"], label
