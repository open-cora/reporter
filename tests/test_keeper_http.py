"""Every call this reporter makes, asserted on the request it builds.

Driven through a transport that records instead of sending, so the body,
the path and the headers are all checked without a keeper to talk to and
without this package growing an HTTP library.

Two calls where there were five, and the three that went were the ones
that created a run and found it again. That is the whole of what moving
to a dispatched execution took away from this side: the ids arrive with
the delivery, so there is nothing here to resolve.

**What this does not prove.** That the routes exist and take these
parameters. Nothing readable from here says so: the keeper's OpenAPI document is
generated on demand rather than committed, and importing `apps/keeper` to ask
it would put `keeper` in this project's environment and dissolve the
boundary that makes the reporter a separate deployable. So a rename on
the keeper's side fails there, loudly, in its own path pin, and the person doing
it has to look for callers.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from reporter.adapters.keeper_http import (
    HttpCataloguing,
    HttpFiling,
    HttpReporting,
    dataset_key_for,
)
from reporter.config import from_mapping
from reporter.intents import RegisterDataset, Report, ReportStepRun
from reporter.seams import (
    DisagreedError,
    Entry,
    Extent,
    Manifest,
    RefusedError,
    UnavailableError,
)
from tests._fakes import Answer, Recorder

AN_EXECUTION = UUID("01a0ba64-8f95-7ad1-a7a7-44124ff3afd5")
A_STEP = UUID("01a0ba65-df83-7501-aa5d-3e2318ef956c")
A_UID = "5b4f40e7-1b2c-4d3e-8f90-abcdef012345"
AN_INSTANT = datetime(2026, 9, 19, 10, 2, 11, tzinfo=UTC)

CONFIG = from_mapping({"keeper": {"base_url": "https://keeper.example", "token": "a-token"}})

RUN_PATH = f"/executions/{AN_EXECUTION}/steps/{A_STEP}/run"


def reporting_answering(*answers: Answer) -> tuple[HttpReporting, Recorder]:
    recorder = Recorder(answers=list(answers))
    return HttpReporting(recorder, CONFIG.base_url, CONFIG.token), recorder


def filing_answering(*answers: Answer) -> tuple[HttpFiling, Recorder]:
    recorder = Recorder(answers=list(answers))
    return HttpFiling(recorder, CONFIG.base_url, CONFIG.token, A_SCHEME), recorder


def cataloguing_answering(*answers: Answer) -> tuple[HttpCataloguing, Recorder]:
    recorder = Recorder(answers=list(answers))
    return HttpCataloguing(recorder, CONFIG.base_url, CONFIG.token, A_SCHEME), recorder


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
    reporting, recorder = reporting_answering(Answer(204))

    reporting.record(a_report())

    sent = recorder.sent[0]
    assert sent.method == "POST"
    assert sent.url == f"https://keeper.example{RUN_PATH}"


def test_a_report_puts_the_verb_in_the_body_rather_than_the_path() -> None:
    """One endpoint for six reports, which is the keeper's choice made for this
    caller: a reporter turns each document into whichever of six it is, so
    a path per verb would make it build a URL by lookup."""
    reporting, recorder = reporting_answering(Answer(204), Answer(204))

    reporting.record(a_report("Started"))
    reporting.record(a_report("Completed", origin="stop"))

    assert [(s.json or {})["reported"] for s in recorder.sent] == ["Started", "Completed"]
    assert {s.url for s in recorder.sent} == {f"https://keeper.example{RUN_PATH}"}


def test_a_report_carries_the_engines_own_id_on_every_one_of_them() -> None:
    """The keeper records it on a start and ignores it elsewhere, which is stated
    on that route. Sending it always is what lets the store be asked about
    the same run on the delivery that ends it."""
    reporting, recorder = reporting_answering(Answer(204))

    reporting.record(a_report("Paused", origin="event"))

    assert (recorder.sent[0].json or {})["engine_reference"] == A_UID


def test_a_report_with_no_time_sends_a_null_rather_than_dropping_the_field() -> None:
    """Sending null says the delivery carried no time, and the keeper stamps the
    moment it was told. Omitting the field says the same thing less clearly."""
    reporting, recorder = reporting_answering(Answer(204))
    reporting.record(a_report(occurred_at=None))

    assert (recorder.sent[0].json or {})["occurred_at"] is None


def test_a_report_that_does_not_follow_raises_disagreed_rather_than_passing() -> None:
    """The refusal a redelivered stop produces, and the only seam that
    produces it. It is expected and it is still an exception, because only
    the caller knows whether it expected one.

    `detail` is what the keeper said and nothing this adapter added,
    because the session copies it onto an `Unchanged` and a route
    prepended here would end up in the record.
    """
    reporting, _ = reporting_answering(Answer(409, text="has Completed from its engine"))

    with pytest.raises(DisagreedError) as disagreement:
        reporting.record(a_report("Completed", origin="stop"))

    assert disagreement.value.detail == "has Completed from its engine"


def test_a_report_sends_no_idempotency_key() -> None:
    """Deliberate. The aggregate already refuses a repeated report with a
    409 naming the engine state it holds, which distinguishes a redelivery
    from a reporter that has lost track of a run. A cached success would
    not."""
    reporting, recorder = reporting_answering(Answer(204))
    reporting.record(a_report("Paused", origin="event"))

    assert "Idempotency-Key" not in (recorder.sent[0].headers or {})


@pytest.mark.parametrize("status", [400, 403, 404])
def test_a_report_answered_with_a_settled_no_is_refused(status: int) -> None:
    reporting, _ = reporting_answering(Answer(status, text="no"))

    with pytest.raises(RefusedError) as refusal:
        reporting.record(a_report())

    assert str(status) in str(refusal.value)
    assert RUN_PATH in str(refusal.value)


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_a_report_answered_with_a_passing_no_is_unavailable(status: int) -> None:
    """The distinction the core no longer makes for itself.

    Whether waiting could change an answer is knowledge about HTTP, so it
    is settled here and travels upward as a class. A 500 used to arrive
    above as the same exception a 400 did, with a number on it that two
    separate callers then had to interpret the same way.
    """
    reporting, _ = reporting_answering(Answer(status, text="later"))

    with pytest.raises(UnavailableError):
        reporting.record(a_report())


def test_a_request_that_never_arrives_is_unavailable_rather_than_escaping() -> None:
    """A worker that dies looks like a beamline that is not running.

    The relay retries one class and nothing else, so a transport failure
    that travelled as its library's own exception would pass through
    every handler above and kill the thread silently.
    """

    class Unreachable:
        def post(self, url: str, **_: Any) -> Answer:
            raise OSError("connection reset")

    reporting = HttpReporting(Unreachable(), CONFIG.base_url, CONFIG.token)

    with pytest.raises(UnavailableError, match="did not arrive"):
        reporting.record(a_report())


# Registering a dataset. The store half is `tests/test_stores.py`; these
# check only what this package sends to the keeper once it has a location.

A_DATASET = UUID("01a0ba66-1c41-7f02-9e48-5b7a0c6d2e19")
A_PATH = f"raw/{A_UID}"
A_SCHEME = "tiled-node-path"


def test_register_dataset_posts_the_address_the_store_gave_and_returns_the_id() -> None:
    filing, recorder = filing_answering(Answer(201, {"dataset_id": str(A_DATASET)}))

    registered = filing.record(a_dataset(AN_INSTANT))

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
    """An execution may run several times and each writes its own data,
    which at a tomography beamline is the sample position. A body naming
    only the execution would lose which."""
    filing, recorder = filing_answering(Answer(201, {"dataset_id": str(A_DATASET)}))

    filing.record(a_dataset())

    body = recorder.sent[0].json or {}
    assert body["step_id"] == str(A_STEP)


def test_register_dataset_sends_a_key_derived_from_the_step_and_the_address() -> None:
    filing, recorder = filing_answering(Answer(201, {"dataset_id": str(A_DATASET)}))

    filing.record(a_dataset())

    sent = recorder.sent[0]
    assert sent.headers is not None
    assert sent.headers["Idempotency-Key"] == dataset_key_for(A_STEP, A_PATH)
    assert sent.headers["Authorization"] == "Bearer a-token"


def test_two_datasets_from_one_acquisition_are_keyed_apart() -> None:
    """Why the address is in the key. Keyed on the step alone, the
    second of these would come back holding the first one's id."""
    primary = dataset_key_for(A_STEP, f"{A_PATH}/primary")
    darks = dataset_key_for(A_STEP, f"{A_PATH}/darkfields")

    assert primary != darks


def test_two_runs_writing_one_address_are_keyed_apart() -> None:
    """Why the step is in the key, which it was not until a run showed it.

    An engine whose scan number resets writes over yesterday's name.
    Keyed on the address alone the second registration returns the
    first record's id and appends no event, so that run is recorded as
    having produced data nobody filed, and the caller sees a success.
    """
    another_step = UUID("01a0ba65-df83-7501-aa5d-3e2318ef9570")

    assert dataset_key_for(A_STEP, A_PATH) != dataset_key_for(another_step, A_PATH)


def test_the_dataset_key_is_the_same_on_every_recomputation() -> None:
    """Derived rather than remembered, which is what makes a redelivery safe
    after a restart that persisted nothing."""
    assert dataset_key_for(A_STEP, "raw/5b4f40e7") == dataset_key_for(A_STEP, "raw/5b4f40e7")
    assert dataset_key_for(A_STEP, "raw/5b4f40e7") != dataset_key_for(A_STEP, "raw/5b4f40e8")
    assert "raw/5b4f40e7" in dataset_key_for(A_STEP, "raw/5b4f40e7")


def test_register_dataset_sends_no_moment_when_the_store_held_no_ending() -> None:
    filing, recorder = filing_answering(Answer(201, {"dataset_id": str(A_DATASET)}))

    filing.record(a_dataset())

    sent = recorder.sent[0]
    assert sent.json is not None
    assert sent.json["occurred_at"] is None


@pytest.mark.parametrize("status", [400, 403, 404, 422])
def test_filing_answered_with_a_settled_no_is_refused(status: int) -> None:
    filing, _ = filing_answering(Answer(status, text="no"))

    with pytest.raises(RefusedError) as refusal:
        filing.record(a_dataset())

    assert str(status) in str(refusal.value)
    assert "/datasets" in str(refusal.value)


@pytest.mark.parametrize("status", [429, 500, 503])
def test_filing_answered_with_a_passing_no_is_unavailable(status: int) -> None:
    filing, _ = filing_answering(Answer(status, text="later"))

    with pytest.raises(UnavailableError):
        filing.record(a_dataset())


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
    if path == "run":
        reporting, recorder = reporting_answering(success)
        reporting.record(a_report())
    else:
        filing, recorder = filing_answering(success)
        filing.record(a_dataset())

    assert (recorder.sent[0].headers or {})["Authorization"] == "Bearer a-token"


A_MANIFEST = Manifest(
    convention="dxchange",
    entries=(
        Entry(
            path="/exchange/data",
            extent=Extent(shape=(1800, 2048, 2048), capacity=(2000, 2048, 2048), dtype="uint16"),
            role="projections",
        ),
        Entry(path="/measurement/sample", extent=None, role="experiment-context"),
    ),
)


def test_a_description_posts_to_the_dataset_filing_returned() -> None:
    cataloguing, recorder = cataloguing_answering(Answer(204, {}))

    cataloguing.record(A_DATASET, A_PATH, A_MANIFEST)

    sent = recorder.sent[0]
    assert sent.method == "POST"
    assert sent.url == f"https://keeper.example/datasets/{A_DATASET}/manifests"


def test_a_description_names_the_copy_that_was_opened_in_the_configured_scheme() -> None:
    cataloguing, recorder = cataloguing_answering(Answer(204, {}))

    cataloguing.record(A_DATASET, A_PATH, A_MANIFEST)

    sent = recorder.sent[0]
    assert sent.json is not None
    assert sent.json["external_ref"] == {"scheme": A_SCHEME, "value": A_PATH}


def test_an_entry_nobody_measured_sends_a_null_extent_rather_than_nulls_inside_one() -> None:
    """The far side reads the two differently and so should the wire.

    No extent is nobody having measured. An extent of nulls would be
    somebody having measured nothing, which is a claim this never makes.
    """
    cataloguing, recorder = cataloguing_answering(Answer(204, {}))

    cataloguing.record(A_DATASET, A_PATH, A_MANIFEST)

    sent = recorder.sent[0]
    assert sent.json is not None
    assert sent.json["entries"] == [
        {
            "path": "/exchange/data",
            "role": "projections",
            "extent": {
                "shape": [1800, 2048, 2048],
                "capacity": [2000, 2048, 2048],
                "dtype": "uint16",
            },
        },
        {"path": "/measurement/sample", "role": "experiment-context", "extent": None},
    ]


def test_a_description_carries_no_time_because_it_was_taken_here_and_now() -> None:
    """The other two relay a moment from elsewhere. This one does not."""
    cataloguing, recorder = cataloguing_answering(Answer(204, {}))

    cataloguing.record(A_DATASET, A_PATH, A_MANIFEST)

    sent = recorder.sent[0]
    assert sent.json is not None
    assert "occurred_at" not in sent.json


def test_a_description_sends_no_idempotency_key() -> None:
    """The far side tells a retry from a second look by what it says."""
    cataloguing, recorder = cataloguing_answering(Answer(204, {}))

    cataloguing.record(A_DATASET, A_PATH, A_MANIFEST)

    sent = recorder.sent[0]
    assert sent.headers is not None
    assert "Idempotency-Key" not in sent.headers


def test_a_description_the_record_already_holds_raises_disagreed() -> None:
    cataloguing, _recorder = cataloguing_answering(Answer(409, {}))

    with pytest.raises(DisagreedError):
        cataloguing.record(A_DATASET, A_PATH, A_MANIFEST)


@pytest.mark.parametrize("status", [403, 404, 422])
def test_a_description_answered_with_a_settled_no_is_refused(status: int) -> None:
    cataloguing, _recorder = cataloguing_answering(Answer(status, {}))

    with pytest.raises(RefusedError):
        cataloguing.record(A_DATASET, A_PATH, A_MANIFEST)


@pytest.mark.parametrize("status", [429, 500, 503])
def test_a_description_answered_with_a_passing_no_is_unavailable(status: int) -> None:
    cataloguing, _recorder = cataloguing_answering(Answer(status, {}))

    with pytest.raises(UnavailableError):
        cataloguing.record(A_DATASET, A_PATH, A_MANIFEST)
