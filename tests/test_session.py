"""Whole captured scenarios, driven from document to request.

The closest thing to an end-to-end run this project has that needs no
engine. Each test feeds documents a real engine emitted through a real
`Translator` into a real `Session` over a real `ArocClient`, and asserts
the outcomes. Only the socket is fake.

The two are composed by `documents_into`, which is the composition the
entrypoint uses, so these exercise the wiring as well as the parts.

This is what `replay.py` does by printing a report and reading it. The
difference is that a change breaking one of these fails a run.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, get_args
from uuid import UUID

import pytest

from reporter.client import ArocClient, RequestRefusedError
from reporter.config import from_mapping
from reporter.intents import Verb
from reporter.outcomes import Held, Kept, Moved, Outcome, Recorded, Skipped, Unchanged
from reporter.relay import Handle
from reporter.session import ENDINGS, Session, is_worth_retrying
from reporter.stores import Location, StoreRefusedError
from reporter.wire import documents_into
from tests._fakes import Answer, Routed, Store

CAPTURED = Path(__file__).parent / "documents.json"

A_PLAN = UUID("01a0ba64-8f95-7ad1-a7a7-44124ff3afd5")
A_RUN = UUID("01a0ba65-df83-7501-aa5d-3e2318ef956c")

PLAN_NAMES = ("count", "_plain_plan", "_pausing_plan", "_failing_plan")
"""Every plan name the capture uses, so a scenario is not refused for the
wrong reason. A deployment's map is written by an operator; this one is
written from the fixture."""

CONFIG = from_mapping(
    {
        "aroc": {
            "base_url": "https://aroc.example",
            "token": "a-token",
            "external_ref_scheme": "engine-run-uid",
        },
        "plans": dict.fromkeys(PLAN_NAMES, str(A_PLAN)),
    }
)


def captured() -> dict[str, Any]:
    return json.loads(CAPTURED.read_text(encoding="utf-8"))


def scenarios() -> list[str]:
    return sorted(captured())


def deliveries(scenario: str) -> list[tuple[str, dict[str, Any]]]:
    entries: list[dict[str, Any]] = captured()[scenario]["documents"]
    return [(str(entry["name"]), dict(entry["doc"])) for entry in entries]


def session_over(**answers: list[Answer]) -> tuple[Handle, Routed]:
    """A translator and a session on a transport answering as the test says.

    Defaults are the happy path, so a test overrides only the call it is
    about.
    """
    routed = Routed(
        report=answers.get("report") or [Answer(201, {"run_id": str(A_RUN)})],
        move=answers.get("move") or [Answer(204)],
        find=answers.get("find") or [Answer(200, {"items": []})],
    )
    return documents_into(Session(ArocClient(routed, CONFIG), CONFIG)), routed


def drive(scenario: str, handle: Handle) -> list[Outcome]:
    return [handle(name, document) for name, document in deliveries(scenario)]


def test_the_capture_holds_scenarios_to_range_over() -> None:
    """Guard the enumeration: an empty file makes every check below vacuous."""
    assert scenarios(), f"{CAPTURED} carries no scenarios, so nothing is driven."


@pytest.mark.parametrize("scenario", scenarios())
def test_a_scenario_records_one_run_and_ends_it_once(scenario: str) -> None:
    handle, _ = session_over()
    outcomes = drive(scenario, handle)

    assert len([o for o in outcomes if isinstance(o, Recorded)]) == 1
    assert len([o for o in outcomes if isinstance(o, Moved)]) >= 1
    assert not [o for o in outcomes if isinstance(o, Held)]


@pytest.mark.parametrize("scenario", scenarios())
def test_a_scenario_sends_one_post_per_thing_that_happened(scenario: str) -> None:
    """Nothing is sent twice, and the descriptors send nothing at all."""
    handle, routed = session_over()
    outcomes = drive(scenario, handle)

    acted = [o for o in outcomes if isinstance(o, (Recorded, Moved))]
    assert len(routed.calls("POST")) == len(acted)


def test_a_full_pause_and_resume_produces_the_outcomes_in_order() -> None:
    handle, _ = session_over()

    outcomes = drive("pause_resume_complete", handle)

    assert [type(o).__name__ for o in outcomes] == [
        "Recorded",
        "Skipped",
        "Moved",
        "Moved",
        "Moved",
    ]
    assert [o.verb for o in outcomes if isinstance(o, Moved)] == ["pause", "resume", "complete"]


def test_a_descriptor_sends_nothing() -> None:
    handle, routed = session_over()
    outcome = handle("descriptor", {"uid": "d1", "run_start": "r1"})

    assert isinstance(outcome, Skipped)
    assert routed.sent == []


def test_a_run_whose_plan_is_not_configured_is_held_and_not_authored() -> None:
    """The refusal that makes the plan map safe. An adapter cannot derive a
    correct schema from one invocation, so a name with no entry produces
    nothing rather than a plan nobody asked for."""
    handle, routed = session_over()

    outcome = handle("start", {"uid": "r1", "plan_name": "unheard-of", "time": 1.0})

    assert isinstance(outcome, Held)
    assert "unheard-of" in outcome.reason
    assert routed.sent == []


def test_a_transition_for_a_run_aroc_never_heard_of_is_held() -> None:
    """What a reporter joining mid-run finds: the start went to whoever was
    listening before it. The lookup is made and comes back empty."""
    handle, routed = session_over(find=[Answer(200, {"items": []})])
    handle("descriptor", {"uid": "d1", "run_start": "r1"})

    outcome = handle("stop", {"run_start": "r1", "exit_status": "success"})

    assert isinstance(outcome, Held)
    assert "r1" in outcome.reason
    assert routed.calls("GET")


def test_a_restarted_reporter_recovers_a_run_from_aroc() -> None:
    """The whole reason the read side landed before this did. A session with
    no memory resolves an engine uid through `GET /runs` and carries on."""
    handle, routed = session_over(find=[Answer(200, {"items": [{"run_id": str(A_RUN)}]})])
    handle("descriptor", {"uid": "d1", "run_start": "r1"})

    outcome = handle("stop", {"run_start": "r1", "exit_status": "success"})

    assert outcome == Moved(A_RUN, "complete")
    assert len(routed.calls("GET")) == 1


def test_a_run_reported_in_this_session_is_not_looked_up_again() -> None:
    """The lookup is recovery, not the normal path. One per restart, not one
    per transition."""
    handle, routed = session_over()
    drive("pause_resume_complete", handle)

    assert routed.calls("GET") == []


def test_a_run_is_looked_up_again_after_it_has_ended() -> None:
    """A finished run leaves the map, so the map tracks live runs rather
    than growing for the life of the stream. A late document for it then
    reads as unattributable, which is what it is."""
    handle, routed = session_over(find=[Answer(200, {"items": []})])
    drive("completes", handle)
    before = len(routed.calls("GET"))

    stop = next(doc for name, doc in deliveries("completes") if name == "stop")
    handle("stop", dict(stop))

    assert len(routed.calls("GET")) == before + 1


def test_a_redelivered_ending_leaves_the_record_unchanged() -> None:
    """The shape of a replay. AROC's 409 names the state the run is in, and
    that is a settled answer rather than something to alert on."""
    handle, _ = session_over(
        move=[Answer(409, text="Run cannot be completed: it is already Completed")]
    )
    outcomes = drive("completes", handle)

    ending = outcomes[-1]
    assert isinstance(ending, Unchanged)
    assert "already Completed" in ending.detail


def test_a_refusal_the_reporter_cannot_fix_is_held_rather_than_raised() -> None:
    """A missing grant looks the same on every document, so the caller
    should move past this one and be told, not retry it forever."""
    handle, _ = session_over(report=[Answer(403, text="not permitted")])

    outcome = handle("start", {"uid": "r1", "plan_name": "count", "time": 1.0})

    assert isinstance(outcome, Held)
    assert "403" in outcome.reason


def test_a_refusal_that_might_pass_later_raises_so_the_caller_waits() -> None:
    """The distinction a checkpoint turns on. An outcome says the document
    is finished with; an exception says ask again."""
    handle, _ = session_over(report=[Answer(503, text="unavailable")])

    with pytest.raises(RequestRefusedError) as refusal:
        handle("start", {"uid": "r1", "plan_name": "count", "time": 1.0})

    assert refusal.value.status == 503


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_a_status_worth_waiting_on_is_recognised(status: int) -> None:
    assert is_worth_retrying(status)


@pytest.mark.parametrize("status", [400, 403, 404, 409, 422])
def test_a_status_that_will_not_change_is_not(status: int) -> None:
    assert not is_worth_retrying(status)


def test_an_unmappable_document_is_held_and_names_the_document() -> None:
    """An ending nobody recognises is a bug here or a fourth exit status
    upstream, and either is worth somebody's attention."""
    handle, routed = session_over()

    outcome = handle("stop", {"run_start": "r1", "exit_status": "vaporised"})

    assert isinstance(outcome, Held)
    assert outcome.origin == "stop"
    assert routed.sent == []


def test_the_run_a_scenario_reports_carries_the_engines_own_id() -> None:
    """The external reference is what makes a restart recoverable, so it has
    to be on the record rather than only in this process."""
    handle, routed = session_over()
    drive("real_plan", handle)

    body = routed.calls("POST")[0].json or {}
    start = next(doc for name, doc in deliveries("real_plan") if name == "start")
    assert body["external_ref"] == {"scheme": "engine-run-uid", "value": start["uid"]}


def test_every_ending_names_a_verb_that_exists() -> None:
    """`ENDINGS` used to be derived from one engine's exit statuses, which
    made an AROC fact look like the engine's. Written out, it can drift, so
    this is what stops a typo becoming a run that is never forgotten."""
    assert set(get_args(Verb)) >= ENDINGS


def test_a_run_is_forgotten_after_every_ending_and_no_other_verb() -> None:
    """The set is not just well formed, it is the right one: a run ends on
    three verbs and continues on the two that cycle."""
    assert {"complete", "abort", "fail"} == ENDINGS
    assert set(get_args(Verb)) - ENDINGS == {"pause", "resume"}


# The dataset leg. Everything above runs with no store configured, which is
# also a deployment, so these add a store rather than changing the default.

A_DATASET = UUID("01a0ba66-1c41-7f02-9e48-5b7a0c6d2e19")

STORE_CONFIG = from_mapping(
    {
        "aroc": {
            "base_url": "https://aroc.example",
            "token": "a-token",
            "external_ref_scheme": "engine-run-uid",
        },
        "plans": dict.fromkeys(PLAN_NAMES, str(A_PLAN)),
        "store": {
            "base_url": "https://store.example",
            "root": "raw",
            "external_ref_scheme": "tiled-node-path",
        },
    }
)

AN_ENDING = datetime(2026, 9, 20, 11, 30, tzinfo=UTC)


def uid_of(scenario: str) -> str:
    start = next(doc for name, doc in deliveries(scenario) if name == "start")
    return str(start["uid"])


def session_with_store(store: Store, **answers: list[Answer]) -> tuple[Handle, Routed]:
    """The same wiring as `session_over`, with the dataset leg switched on."""
    routed = Routed(
        report=answers.get("report") or [Answer(201, {"run_id": str(A_RUN)})],
        move=answers.get("move") or [Answer(204)],
        find=answers.get("find") or [Answer(200, {"items": []})],
        register=answers.get("register") or [Answer(201, {"dataset_id": str(A_DATASET)})],
    )
    session = Session(ArocClient(routed, STORE_CONFIG), STORE_CONFIG, store)
    return documents_into(session), routed


def store_holding(scenario: str, *, occurred_at: datetime | None = AN_ENDING) -> Store:
    uid = uid_of(scenario)
    return Store({uid: Location(path=f"raw/{uid}", occurred_at=occurred_at)})


def test_a_session_with_no_store_never_asks_one_and_reports_the_move() -> None:
    """The default deployment, unchanged by the leg existing."""
    handle, routed = session_over()
    outcomes = drive("completes", handle)

    assert isinstance(outcomes[-1], Moved)
    assert not routed.calls("POST", containing="/datasets")


def test_an_ending_registers_what_the_store_holds_and_reports_it_kept() -> None:
    store = store_holding("completes")
    handle, routed = session_with_store(store)

    outcomes = drive("completes", handle)

    ending = outcomes[-1]
    assert isinstance(ending, Kept)
    assert ending.dataset_id == A_DATASET
    assert ending.external_ref_value == f"raw/{uid_of('completes')}"
    assert ending.verb == "complete"
    assert store.asked == [uid_of("completes")]
    assert len(routed.calls("POST", containing="/datasets")) == 1


@pytest.mark.parametrize("scenario", scenarios())
def test_every_ending_registers_exactly_one_dataset(scenario: str) -> None:
    """Including the three that produced no data. A node holding nothing is
    a fact, and it is the one somebody looking for missing data needs."""
    handle, routed = session_with_store(store_holding(scenario))

    outcomes = drive(scenario, handle)

    assert len([o for o in outcomes if isinstance(o, Kept)]) == 1
    assert len(routed.calls("POST", containing="/datasets")) == 1
    assert not [o for o in outcomes if isinstance(o, Held)]


def test_a_pause_is_not_an_ending_so_nothing_is_registered_for_it() -> None:
    store = store_holding("pause_resume_complete")
    handle, routed = session_with_store(store)

    outcomes = drive("pause_resume_complete", handle)

    assert [type(o).__name__ for o in outcomes if isinstance(o, (Moved, Kept))] == [
        "Moved",
        "Moved",
        "Kept",
    ]
    assert len(routed.calls("POST", containing="/datasets")) == 1


def test_the_registration_carries_the_stores_scheme_and_the_endings_moment() -> None:
    handle, routed = session_with_store(store_holding("completes"))

    drive("completes", handle)

    sent = routed.calls("POST", containing="/datasets")[0]
    assert sent.json == {
        "run_id": str(A_RUN),
        "external_ref": {
            "scheme": "tiled-node-path",
            "value": f"raw/{uid_of('completes')}",
        },
        "occurred_at": AN_ENDING.isoformat(),
    }


def test_the_registration_is_keyed_on_the_address_rather_than_the_run() -> None:
    """Two datasets from one run would otherwise share a key, and the second
    would come back holding the first one's id."""
    handle, routed = session_with_store(store_holding("completes"))

    drive("completes", handle)

    sent = routed.calls("POST", containing="/datasets")[0]
    assert sent.headers is not None
    key = sent.headers["Idempotency-Key"]
    assert key == f"register-dataset:raw/{uid_of('completes')}"
    assert uid_of("completes") in key


def test_a_store_holding_no_ending_still_registers_and_lets_aroc_stamp_it() -> None:
    """A node without its stop is a reporter that subscribed before the
    writer. Less true than it could be, and better than nothing."""
    handle, routed = session_with_store(store_holding("completes", occurred_at=None))

    outcomes = drive("completes", handle)

    assert isinstance(outcomes[-1], Kept)
    sent = routed.calls("POST", containing="/datasets")[0]
    assert sent.json is not None
    assert sent.json["occurred_at"] is None


def test_a_run_the_store_holds_nothing_for_is_held_and_names_the_run() -> None:
    handle, routed = session_with_store(Store())

    outcomes = drive("completes", handle)

    ending = outcomes[-1]
    assert isinstance(ending, Held)
    assert uid_of("completes") in ending.reason
    assert not routed.calls("POST", containing="/datasets")


def test_a_store_refusing_for_good_is_held_rather_than_raised() -> None:
    store = Store(refusal=StoreRefusedError(403, "not permitted", url="https://store.example/x"))
    handle, _ = session_with_store(store)

    outcomes = drive("completes", handle)

    ending = outcomes[-1]
    assert isinstance(ending, Held)
    assert "403" in ending.reason


def test_a_store_having_a_bad_moment_raises_so_the_caller_waits() -> None:
    """The relay retries this. An outcome would advance past it instead."""
    store = Store(refusal=StoreRefusedError(503, "later", url="https://store.example/x"))
    handle, _ = session_with_store(store)

    with pytest.raises(StoreRefusedError):
        drive("completes", handle)


def test_aroc_refusing_the_registration_is_held_after_the_run_has_moved() -> None:
    """The cost of one outcome per intent, pinned rather than left to be
    discovered: the move happened and the summary will not say so."""
    handle, routed = session_with_store(
        store_holding("completes"), register=[Answer(403, text="not permitted")]
    )

    outcomes = drive("completes", handle)

    ending = outcomes[-1]
    assert isinstance(ending, Held)
    assert not [o for o in outcomes if isinstance(o, Moved)]
    assert len(routed.calls("POST", containing="/runs/")) == 1


def test_a_redelivered_ending_still_registers_the_dataset() -> None:
    """The first delivery may have recorded the ending and died before the
    data. The retry key makes asking again free."""
    handle, routed = session_with_store(
        store_holding("completes"),
        move=[Answer(409, text="Run cannot be completed: it is already Completed")],
    )

    outcomes = drive("completes", handle)

    assert isinstance(outcomes[-1], Kept)
    assert len(routed.calls("POST", containing="/datasets")) == 1


def test_a_redelivered_ending_the_store_lost_reports_the_decline_it_got() -> None:
    """With nothing to register, the 409 is still the answer worth giving."""
    handle, _ = session_with_store(Store(), move=[Answer(409, text="already Completed")])

    outcomes = drive("completes", handle)

    assert isinstance(outcomes[-1], Held)


def test_a_store_lookup_without_a_store_table_is_refused_at_construction() -> None:
    """The two halves of the configuration cannot disagree, because one of
    them carries the scheme the other's addresses belong to."""
    with pytest.raises(ValueError, match="store"):
        Session(ArocClient(Routed(report=[], move=[]), CONFIG), CONFIG, Store())
