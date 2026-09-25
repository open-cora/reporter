"""Every call this reporter makes, asserted on the request it builds.

Driven through a transport that records instead of sending, so the body,
the path and the headers are all checked without an AROC to talk to and
without this package growing an HTTP library.

Two calls where there were five, and the three that went were the ones
that created a run and found it again. That is the whole of what moving
to a dispatched execution took away from this side: the ids arrive with
the delivery, so there is nothing here to resolve.

**What this does not prove.** That the routes exist and take these
parameters. Nothing readable from here says so: AROC's OpenAPI document is
generated on demand rather than committed, and importing `apps/api` to ask
it would put `aroc` in this project's environment and dissolve the
boundary that makes the reporter a separate deployable. So a rename on
AROC's side fails there, loudly, in its own path pin, and the person doing
it has to look for callers.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from reporter.client import KeeperClient, RequestRefusedError, dataset_key_for
from reporter.config import from_mapping
from reporter.intents import RegisterDataset, Report, ReportStepRun
from tests._fakes import Answer, Recorder

AN_EXECUTION = UUID("01a0ba64-8f95-7ad1-a7a7-44124ff3afd5")
A_STEP = UUID("01a0ba65-df83-7501-aa5d-3e2318ef956c")
A_UID = "5b4f40e7-1b2c-4d3e-8f90-abcdef012345"
AN_INSTANT = datetime(2026, 9, 19, 10, 2, 11, tzinfo=UTC)

CONFIG = from_mapping({"keeper": {"base_url": "https://keeper.example", "token": "a-token"}})

RUN_PATH = f"/executions/{AN_EXECUTION}/steps/{A_STEP}/run"


def client_answering(*answers: Answer) -> tuple[KeeperClient, Recorder]:
    recorder = Recorder(answers=list(answers))
    return KeeperClient(recorder, CONFIG), recorder


def a_report(reported: Report = "Started", **overrides: Any) -> ReportStepRun:
    fields: dict[str, Any] = {
        "execution_id": AN_EXECUTION,
        "step_id": A_STEP,
        "reported": reported,
        "engine_reference": A_UID,
        "occurred_at": AN_INSTANT,
        "origin": "start",
    }
    return ReportStepRun(**{**fields, **overrides})


def a_dataset(at: datetime | None = None) -> RegisterDataset:
    return RegisterDataset(
        execution_id=AN_EXECUTION,
        step_id=A_STEP,
        external_ref_value=A_PATH,
        occurred_at=at,
        origin="stop",
    )


def test_a_report_posts_to_the_step_the_intent_names() -> None:
    """The execution and the step are both in the path, which is what makes
    a step addressable at all: it has no stream of its own."""
    client, recorder = client_answering(Answer(204))

    client.report_step_run(a_report())

    sent = recorder.sent[0]
    assert sent.method == "POST"
    assert sent.url == f"https://keeper.example{RUN_PATH}"


def test_a_report_puts_the_verb_in_the_body_rather_than_the_path() -> None:
    """One endpoint for six reports, which is AROC's choice made for this
    caller: a reporter turns each document into whichever of six it is, so
    a path per verb would make it build a URL by lookup."""
    client, recorder = client_answering(Answer(204), Answer(204))

    client.report_step_run(a_report("Started"))
    client.report_step_run(a_report("Completed", origin="stop"))

    assert [(s.json or {})["reported"] for s in recorder.sent] == ["Started", "Completed"]
    assert {s.url for s in recorder.sent} == {f"https://keeper.example{RUN_PATH}"}


def test_a_report_carries_the_engines_own_id_on_every_one_of_them() -> None:
    """AROC records it on a start and ignores it elsewhere, which is stated
    on that route. Sending it always is what lets the store be asked about
    the same run on the delivery that ends it."""
    client, recorder = client_answering(Answer(204))

    client.report_step_run(a_report("Paused", origin="event"))

    assert (recorder.sent[0].json or {})["engine_reference"] == A_UID


def test_a_report_with_no_time_sends_a_null_rather_than_dropping_the_field() -> None:
    """Sending null says the delivery carried no time, and AROC stamps the
    moment it was told. Omitting the field says the same thing less clearly."""
    client, recorder = client_answering(Answer(204))
    client.report_step_run(a_report(occurred_at=None))

    assert (recorder.sent[0].json or {})["occurred_at"] is None


def test_a_report_that_does_not_follow_raises_a_409_rather_than_passing() -> None:
    """The refusal a redelivered stop produces. It is expected and it is
    still an exception, because only the caller knows whether it expected
    one."""
    client, _ = client_answering(Answer(409, text="has Completed from its engine"))

    with pytest.raises(RequestRefusedError) as refusal:
        client.report_step_run(a_report("Completed", origin="stop"))

    assert refusal.value.status == 409
    assert refusal.value.path == RUN_PATH


def test_a_report_sends_no_idempotency_key() -> None:
    """Deliberate. The aggregate already refuses a repeated report with a
    409 naming the engine state it holds, which distinguishes a redelivery
    from a reporter that has lost track of a run. A cached success would
    not."""
    client, recorder = client_answering(Answer(204))
    client.report_step_run(a_report("Paused", origin="event"))

    assert "Idempotency-Key" not in (recorder.sent[0].headers or {})


@pytest.mark.parametrize("status", [400, 403, 404, 500])
def test_a_report_refuses_on_anything_but_a_204(status: int) -> None:
    client, _ = client_answering(Answer(status, text="no"))

    with pytest.raises(RequestRefusedError) as refusal:
        client.report_step_run(a_report())

    assert refusal.value.status == status
    assert refusal.value.path == RUN_PATH


# Registering a dataset. The store half is `tests/test_stores.py`; these
# check only what this package sends to AROC once it has a location.

A_DATASET = UUID("01a0ba66-1c41-7f02-9e48-5b7a0c6d2e19")
A_PATH = f"raw/{A_UID}"
A_SCHEME = "tiled-node-path"


def test_register_dataset_posts_the_address_the_store_gave_and_returns_the_id() -> None:
    client, recorder = client_answering(Answer(201, {"dataset_id": str(A_DATASET)}))

    registered = client.register_dataset(a_dataset(AN_INSTANT), scheme=A_SCHEME)

    assert registered == A_DATASET
    sent = recorder.sent[0]
    assert sent.method == "POST"
    assert sent.url == "https://keeper.example/datasets"
    assert sent.json == {
        "execution_id": str(AN_EXECUTION),
        "step_id": str(A_STEP),
        "external_ref": {"scheme": A_SCHEME, "value": A_PATH},
        "occurred_at": AN_INSTANT.isoformat(),
    }


def test_register_dataset_names_the_acquisition_and_not_the_traversal() -> None:
    """An execution may acquire several times and each writes its own data,
    which at a tomography beamline is the sample position. A body naming
    only the execution would lose which."""
    client, recorder = client_answering(Answer(201, {"dataset_id": str(A_DATASET)}))

    client.register_dataset(a_dataset(), scheme=A_SCHEME)

    body = recorder.sent[0].json or {}
    assert body["step_id"] == str(A_STEP)


def test_register_dataset_sends_a_key_derived_from_the_address_not_the_step() -> None:
    client, recorder = client_answering(Answer(201, {"dataset_id": str(A_DATASET)}))

    client.register_dataset(a_dataset(), scheme=A_SCHEME)

    sent = recorder.sent[0]
    assert sent.headers is not None
    assert sent.headers["Idempotency-Key"] == dataset_key_for(A_PATH)
    assert sent.headers["Authorization"] == "Bearer a-token"


def test_two_datasets_from_one_acquisition_are_keyed_apart() -> None:
    """The whole reason the key names an address. Keyed on the step, the
    second of these would come back holding the first one's id."""
    primary = dataset_key_for(f"{A_PATH}/primary")
    darks = dataset_key_for(f"{A_PATH}/darkfields")

    assert primary != darks


def test_the_dataset_key_is_the_same_on_every_recomputation() -> None:
    """Derived rather than remembered, which is what makes a redelivery safe
    after a restart that persisted nothing."""
    assert dataset_key_for("raw/5b4f40e7") == dataset_key_for("raw/5b4f40e7")
    assert dataset_key_for("raw/5b4f40e7") != dataset_key_for("raw/5b4f40e8")
    assert "raw/5b4f40e7" in dataset_key_for("raw/5b4f40e7")


def test_register_dataset_sends_no_moment_when_the_store_held_no_ending() -> None:
    client, recorder = client_answering(Answer(201, {"dataset_id": str(A_DATASET)}))

    client.register_dataset(a_dataset(), scheme=A_SCHEME)

    sent = recorder.sent[0]
    assert sent.json is not None
    assert sent.json["occurred_at"] is None


@pytest.mark.parametrize("status", [400, 403, 404, 422, 500])
def test_register_dataset_refuses_on_anything_but_a_201(status: int) -> None:
    client, _ = client_answering(Answer(status, text="no"))

    with pytest.raises(RequestRefusedError) as refusal:
        client.register_dataset(a_dataset(), scheme=A_SCHEME)

    assert refusal.value.status == status
    assert refusal.value.path == "/datasets"


@pytest.mark.parametrize(
    ("path", "success"),
    [("run", Answer(204)), ("dataset", Answer(201, {"dataset_id": str(A_DATASET)}))],
    ids=["report_step_run", "register_dataset"],
)
def test_every_write_carries_the_bearer_token(path: str, success: Answer) -> None:
    """A write that authenticates as nobody is refused everything under a
    real policy, and the failure reads as an authorization problem rather
    than a missing header.

    Each call is paired with the status it succeeds on, so the header is
    checked on a write that went through. Feeding both from one list let
    the second case raise on the first case's answer, and the assertion
    underneath never ran.
    """
    client, recorder = client_answering(success)
    if path == "run":
        client.report_step_run(a_report())
    else:
        client.register_dataset(a_dataset(), scheme=A_SCHEME)

    assert (recorder.sent[0].headers or {})["Authorization"] == "Bearer a-token"
