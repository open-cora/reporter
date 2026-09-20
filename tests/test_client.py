"""Every call this reporter makes, asserted on the request it builds.

Driven through a transport that records instead of sending, so the body,
the path, the query and the headers are all checked without an AROC to
talk to and without this package growing an HTTP library.

**What this does not prove.** That the routes exist and take these
parameters. Nothing readable from here says so: AROC's OpenAPI document is
generated on demand rather than committed, and importing `apps/api` to ask
it would put `aroc` in this project's environment and dissolve the
boundary that makes the reporter a separate deployable. So a rename on
AROC's side fails there, loudly, in its own path pin, and the person doing
it has to look for callers. Closing that properly needs one end-to-end
run, which needs a session to run it, which is the landing after this one.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from reporter.client import ArocClient, RequestRefusedError, idempotency_key_for
from reporter.config import from_mapping
from reporter.intents import ReportRun, Transition, Verb
from tests._fakes import Answer, Recorder

A_PLAN = UUID("01a0ba64-8f95-7ad1-a7a7-44124ff3afd5")
A_RUN = UUID("01a0ba65-df83-7501-aa5d-3e2318ef956c")
A_UID = "5b4f40e7-1b2c-4d3e-8f90-abcdef012345"
AN_INSTANT = datetime(2026, 9, 19, 10, 2, 11, tzinfo=UTC)

CONFIG = from_mapping(
    {
        "aroc": {
            "base_url": "https://aroc.example",
            "token": "a-token",
            "external_ref_scheme": "engine-run-uid",
        },
        "plans": {"count": str(A_PLAN)},
    }
)


def client_answering(*answers: Answer) -> tuple[ArocClient, Recorder]:
    recorder = Recorder(answers=list(answers))
    return ArocClient(recorder, CONFIG), recorder


def a_run(**overrides: Any) -> ReportRun:
    fields: dict[str, Any] = {
        "plan_name": "count",
        "parameters": {"num": 2, "detectors": ["det"]},
        "external_ref_value": A_UID,
        "occurred_at": AN_INSTANT,
        "origin": "start",
    }
    return ReportRun(**{**fields, **overrides})


def a_move(verb: Verb, origin: str, at: datetime | None = None) -> Transition:
    return Transition(run_uid=A_UID, verb=verb, occurred_at=at, origin=origin)


def test_reporting_a_run_posts_it_and_returns_the_id_aroc_minted() -> None:
    client, recorder = client_answering(Answer(201, {"run_id": str(A_RUN)}))

    assert client.report_run(a_run(), A_PLAN) == A_RUN

    sent = recorder.sent[0]
    assert sent.method == "POST"
    assert sent.url == "https://aroc.example/runs"
    assert sent.json == {
        "plan_id": str(A_PLAN),
        "parameters": {"num": 2, "detectors": ["det"]},
        "external_ref": {"scheme": "engine-run-uid", "value": A_UID},
        "occurred_at": "2026-09-19T10:02:11+00:00",
    }


def test_reporting_a_run_carries_a_key_derived_from_the_engines_own_id() -> None:
    """The whole of the redelivery fix. Derived rather than remembered, so a
    restart that persisted nothing still recomputes it and the second
    delivery returns the first run rather than making another."""
    client, recorder = client_answering(Answer(201, {"run_id": str(A_RUN)}))
    client.report_run(a_run(), A_PLAN)

    headers = recorder.sent[0].headers or {}
    assert A_UID in headers["Idempotency-Key"]

    client_again, recorder_again = client_answering(Answer(201, {"run_id": str(A_RUN)}))
    client_again.report_run(a_run(), A_PLAN)

    assert (recorder_again.sent[0].headers or {})["Idempotency-Key"] == headers["Idempotency-Key"]


def test_a_run_with_no_time_sends_a_null_rather_than_dropping_the_field() -> None:
    """Sending null says the document carried no time, and AROC stamps the
    moment it was told. Omitting the field says the same thing less clearly."""
    client, recorder = client_answering(Answer(201, {"run_id": str(A_RUN)}))
    client.report_run(a_run(occurred_at=None), A_PLAN)

    assert (recorder.sent[0].json or {})["occurred_at"] is None


def test_a_refused_report_raises_with_the_status_the_caller_needs() -> None:
    client, _ = client_answering(Answer(403, text="not permitted"))

    with pytest.raises(RequestRefusedError) as refusal:
        client.report_run(a_run(), A_PLAN)

    assert refusal.value.status == 403
    assert refusal.value.path == "/runs"


def test_moving_a_run_posts_to_the_verbs_own_path() -> None:
    client, recorder = client_answering(Answer(204))

    client.move_run(A_RUN, a_move("complete", "stop", AN_INSTANT))

    assert recorder.sent[0].url == f"https://aroc.example/runs/{A_RUN}/complete"
    assert (recorder.sent[0].json or {})["occurred_at"] == "2026-09-19T10:02:11+00:00"


def test_moving_a_run_that_already_moved_raises_a_409_rather_than_passing() -> None:
    """The refusal a redelivered stop produces. It is expected and it is
    still an exception, because only the caller knows whether it expected
    one."""
    client, _ = client_answering(Answer(409, text="already Completed"))

    with pytest.raises(RequestRefusedError) as refusal:
        client.move_run(A_RUN, a_move("complete", "stop"))

    assert refusal.value.status == 409


def test_moving_a_run_sends_no_idempotency_key() -> None:
    """Deliberate. The aggregate already refuses a repeated transition with
    a 409 naming the state it is in, which distinguishes a redelivery from
    a reporter that has lost track of a run. A cached success would not."""
    client, recorder = client_answering(Answer(204))
    client.move_run(A_RUN, a_move("pause", "event"))

    assert "Idempotency-Key" not in (recorder.sent[0].headers or {})


def test_finding_a_run_sends_both_halves_of_the_filter() -> None:
    """AROC refuses half a filter with a 400, so sending one is a bug here."""
    client, recorder = client_answering(Answer(200, {"items": [{"run_id": str(A_RUN)}]}))

    assert client.find_run(A_UID) == A_RUN
    assert recorder.sent[0].params == {
        "external_ref_scheme": "engine-run-uid",
        "external_ref_value": A_UID,
    }


def test_finding_a_run_aroc_has_no_record_of_yields_nothing() -> None:
    """For a transition it means the start never arrived, which the caller
    handles. It is not an error here."""
    client, _ = client_answering(Answer(200, {"items": []}))

    assert client.find_run(A_UID) is None


def test_finding_a_run_recorded_twice_takes_the_first() -> None:
    """Nothing stops the same engine run being recorded twice, and AROC
    shows the duplicate rather than hiding it. Choosing is this reporter's
    policy, stated where it is made."""
    second = UUID("01a0ba65-dfab-7b83-afc5-149c9ac89e00")
    client, _ = client_answering(
        Answer(200, {"items": [{"run_id": str(A_RUN)}, {"run_id": str(second)}]})
    )

    assert client.find_run(A_UID) == A_RUN


def test_a_configured_plan_aroc_holds_exists() -> None:
    client, recorder = client_answering(Answer(200, {"plan_id": str(A_PLAN)}))

    assert client.plan_exists(A_PLAN) is True
    assert recorder.sent[0].url == f"https://aroc.example/plans/{A_PLAN}"


def test_a_configured_plan_aroc_does_not_hold_is_absent_rather_than_an_error() -> None:
    """A 404 here is the startup check working: a typo in the plan map,
    found before the first run of the day rather than during it."""
    client, _ = client_answering(Answer(404, text="not found"))

    assert client.plan_exists(A_PLAN) is False


def test_a_plan_check_that_fails_some_other_way_still_raises() -> None:
    """Absent and unreachable are different, and a startup check that
    treated a 500 as absent would report the whole map as typos."""
    client, _ = client_answering(Answer(503, text="unavailable"))

    with pytest.raises(RequestRefusedError) as refusal:
        client.plan_exists(A_PLAN)

    assert refusal.value.status == 503


def _report(client: ArocClient) -> None:
    client.report_run(a_run(), A_PLAN)


def _move(client: ArocClient) -> None:
    client.move_run(A_RUN, a_move("fail", "stop"))


@pytest.mark.parametrize(
    ("call", "success"),
    [(_report, Answer(201, {"run_id": str(A_RUN)})), (_move, Answer(204))],
    ids=["report_run", "move_run"],
)
def test_every_write_carries_the_bearer_token(
    call: Callable[[ArocClient], None], success: Answer
) -> None:
    """A write that authenticates as nobody is refused everything under a
    real policy, and the failure reads as an authorization problem rather
    than a missing header.

    Each call is paired with the status it succeeds on, so the header is
    checked on a write that went through. Feeding both from one list let
    the second case raise on the first case's 201, and the assertion
    underneath never ran.
    """
    client, recorder = client_answering(success)
    call(client)

    assert (recorder.sent[0].headers or {})["Authorization"] == "Bearer a-token"


def test_the_idempotency_key_is_the_same_on_every_recomputation() -> None:
    """Derived rather than remembered, which is what makes a redelivery safe
    after a restart that persisted nothing."""
    assert idempotency_key_for("5b4f40e7") == idempotency_key_for("5b4f40e7")
    assert idempotency_key_for("5b4f40e7") != idempotency_key_for("5b4f40e8")
    assert "5b4f40e7" in idempotency_key_for("5b4f40e7")
