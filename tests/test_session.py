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
from pathlib import Path
from typing import Any, get_args
from uuid import UUID

import pytest

from reporter.__main__ import documents_into
from reporter.client import ArocClient, RequestRefusedError
from reporter.config import from_mapping
from reporter.intents import Verb
from reporter.outcomes import Held, Moved, Outcome, Recorded, Skipped, Unchanged
from reporter.relay import Handle
from reporter.session import ENDINGS, Session, is_worth_retrying
from tests._fakes import Answer, Routed

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
