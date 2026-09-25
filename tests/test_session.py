"""Whole captured scenarios, driven from document to request.

The closest thing to an end-to-end run this project has that needs no
engine. Each test feeds documents a real engine emitted through a real
`Translator` into a real `Session` over a real `KeeperClient`, and asserts
the outcomes. Only the socket is fake.

The two are composed by `documents_into`, which is the composition the
entrypoint uses, so these exercise the wiring as well as the parts.

## The capture is decorated, and that is the point

Nothing a real engine emitted carries an AROC reference, because the
capture was taken by driving an engine directly. `dispatched` puts the
two keys a driver will write onto each scenario's start, which is the one
thing invented here and the only thing a driver invents either.

The undecorated capture is exercised too, because a hand-run scan
reaching this layer must produce requests to nobody.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, get_args
from uuid import UUID

import pytest

from reporter.client import KeeperClient, RequestRefusedError
from reporter.config import from_mapping
from reporter.intents import RegisterDataset, Report
from reporter.outcomes import Held, Kept, Outcome, Relayed, Skipped, Unchanged
from reporter.relay import Handle
from reporter.session import ENDINGS, Session, is_worth_retrying
from reporter.stores import Location, StoreRefusedError
from reporter.translate import KEEPER_METADATA_KEYS
from reporter.wire import documents_into
from tests._fakes import Answer, Routed, Store

CAPTURED = Path(__file__).parent / "documents.json"

AN_EXECUTION = UUID("01a0ba64-8f95-7ad1-a7a7-44124ff3afd5")
A_STEP = UUID("01a0ba65-df83-7501-aa5d-3e2318ef956c")

CONFIG = from_mapping({"keeper": {"base_url": "https://keeper.example", "token": "a-token"}})

RUN_PATH = f"/executions/{AN_EXECUTION}/steps/{A_STEP}/run"


def captured() -> dict[str, Any]:
    return json.loads(CAPTURED.read_text(encoding="utf-8"))


def scenarios() -> list[str]:
    return sorted(captured())


def raw_deliveries(scenario: str) -> list[tuple[str, dict[str, Any]]]:
    entries: list[dict[str, Any]] = captured()[scenario]["documents"]
    return [(str(entry["name"]), dict(entry["doc"])) for entry in entries]


def deliveries(scenario: str) -> list[tuple[str, dict[str, Any]]]:
    """One scenario's documents, as they arrive when AROC dispatched it."""
    execution_key, step_key = KEEPER_METADATA_KEYS
    return [
        (name, {**document, execution_key: str(AN_EXECUTION), step_key: str(A_STEP)})
        if name == "start"
        else (name, document)
        for name, document in raw_deliveries(scenario)
    ]


def session_over(**answers: list[Answer]) -> tuple[Handle, Routed]:
    """A translator and a session on a transport answering as the test says.

    Defaults are the happy path, so a test overrides only the call it is
    about.
    """
    routed = Routed(report=answers.get("report") or [Answer(204)])
    return documents_into(Session(KeeperClient(routed, CONFIG), CONFIG)), routed


def drive(scenario: str, handle: Handle) -> list[Outcome]:
    return [handle(name, document) for name, document in deliveries(scenario)]


def test_the_capture_holds_scenarios_to_range_over() -> None:
    """Guard the enumeration: an empty file makes every check below vacuous."""
    assert scenarios(), f"{CAPTURED} carries no scenarios, so nothing is driven."


@pytest.mark.parametrize("scenario", scenarios())
def test_a_scenario_relays_a_start_and_an_ending_and_holds_nothing(scenario: str) -> None:
    handle, _ = session_over()
    outcomes = drive(scenario, handle)

    relayed = [o for o in outcomes if isinstance(o, Relayed)]
    assert relayed[0].reported == "Started"
    assert relayed[-1].reported in ENDINGS
    assert not [o for o in outcomes if isinstance(o, Held)]


@pytest.mark.parametrize("scenario", scenarios())
def test_a_scenario_sends_one_post_per_thing_that_happened(scenario: str) -> None:
    """Nothing is sent twice, and the descriptors send nothing at all."""
    handle, routed = session_over()
    outcomes = drive(scenario, handle)

    acted = [o for o in outcomes if isinstance(o, Relayed)]
    assert len(routed.calls("POST")) == len(acted)


@pytest.mark.parametrize("scenario", scenarios())
def test_a_scenario_aroc_never_dispatched_sends_nothing_at_all(scenario: str) -> None:
    """The undecorated capture, which is a scan somebody ran by hand.

    Every document is skipped, nothing is held, and no request is built.
    This is the layer where the quiet matters most: a `Held` here would
    reach whoever is on call.
    """
    handle, routed = session_over()
    outcomes = [handle(name, document) for name, document in raw_deliveries(scenario)]

    assert all(isinstance(o, Skipped) for o in outcomes)
    assert routed.sent == []


def test_a_full_pause_and_resume_produces_the_outcomes_in_order() -> None:
    handle, _ = session_over()

    outcomes = drive("pause_resume_complete", handle)

    assert [o.reported for o in outcomes if isinstance(o, Relayed)] == [
        "Started",
        "Paused",
        "Resumed",
        "Completed",
    ]


def test_every_report_in_a_scenario_posts_to_the_same_step() -> None:
    """The reference is read once and carried, so every document of one run
    reaches the same record."""
    handle, routed = session_over()
    drive("pause_resume_complete", handle)

    assert {call.url for call in routed.calls("POST")} == {f"https://keeper.example{RUN_PATH}"}


def test_a_descriptor_sends_nothing() -> None:
    handle, routed = session_over()
    outcome = handle("descriptor", {"uid": "d1", "run_start": "r1"})

    assert isinstance(outcome, Skipped)
    assert routed.sent == []


def test_a_start_with_no_aroc_reference_is_skipped_and_not_held() -> None:
    """Work this system did not dispatch. There is no execution to record
    it against and no way to make one from a document."""
    handle, routed = session_over()

    outcome = handle("start", {"uid": "r1", "plan_name": "count", "time": 1.0})

    assert isinstance(outcome, Skipped)
    assert routed.sent == []


def test_an_ending_for_a_run_this_stream_never_introduced_is_held() -> None:
    """What a reporter joining mid-run finds. Unlike the design this
    replaced there is no lookup behind it: AROC publishes no way to find a
    step by what an engine calls the run it opened, so the report is lost
    and says so."""
    handle, routed = session_over()

    outcome = handle("stop", {"run_start": "r1", "exit_status": "success"})

    assert isinstance(outcome, Held)
    assert "r1" in outcome.reason
    assert routed.sent == []


def test_nothing_in_a_whole_scenario_reads_from_aroc() -> None:
    """The lookup is gone, and this is what says so.

    The fake raises on any GET, so a session that resolved anything would
    fail here rather than quietly making a request nobody expects.
    """
    handle, routed = session_over()
    drive("pause_resume_complete", handle)

    assert routed.calls("GET") == []


def test_a_redelivered_ending_leaves_the_record_unchanged() -> None:
    """The shape of a replay. AROC's 409 names the engine state it holds,
    and that is a settled answer rather than something to alert on."""
    handle, _ = session_over(
        report=[Answer(204), Answer(409, text="has Completed from its engine")]
    )
    outcomes = drive("completes", handle)

    ending = outcomes[-1]
    assert isinstance(ending, Unchanged)
    assert "already" in ending.detail or "Completed" in ending.detail


def test_a_refusal_the_reporter_cannot_fix_is_held_rather_than_raised() -> None:
    """A missing grant looks the same on every document, so the caller
    should move past this one and be told, not retry it forever."""
    handle, _ = session_over(report=[Answer(403, text="not permitted")])

    outcome = handle(*deliveries("completes")[0])

    assert isinstance(outcome, Held)
    assert "403" in outcome.reason


def test_a_step_aroc_does_not_hold_is_held_and_names_the_path() -> None:
    """The reference in the engine's metadata and AROC disagreeing.

    There is no startup check that could have caught it, because the
    reference arrives per document rather than from configuration. This
    is where it surfaces.
    """
    handle, _ = session_over(report=[Answer(404, text="holds no step")])

    outcome = handle(*deliveries("completes")[0])

    assert isinstance(outcome, Held)
    assert "404" in outcome.reason
    assert str(A_STEP) in outcome.reason


def test_a_refusal_that_might_pass_later_raises_so_the_caller_waits() -> None:
    """The distinction a checkpoint turns on. An outcome says the document
    is finished with; an exception says ask again."""
    handle, _ = session_over(report=[Answer(503, text="unavailable")])

    with pytest.raises(RequestRefusedError) as refusal:
        handle(*deliveries("completes")[0])

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


def test_every_ending_names_a_report_that_exists() -> None:
    """`ENDINGS` used to be derived from one engine's exit statuses, which
    made an AROC fact look like the engine's. Written out, it can drift, so
    this is what stops a typo becoming a run whose data is never asked
    for."""
    assert set(get_args(Report)) >= ENDINGS


def test_the_store_is_asked_after_every_ending_and_no_other_report() -> None:
    """The set is not just well formed, it is the right one: an engine is
    done after three of the six and carries on after the other three."""
    assert {"Completed", "Aborted", "Failed"} == ENDINGS
    assert set(get_args(Report)) - ENDINGS == {"Started", "Paused", "Resumed"}


# The dataset leg. Everything above runs with no store configured, which is
# also a deployment, so these add a store rather than changing the default.

A_DATASET = UUID("01a0ba66-1c41-7f02-9e48-5b7a0c6d2e19")

STORE_CONFIG = from_mapping(
    {
        "keeper": {"base_url": "https://keeper.example", "token": "a-token"},
        "store": {
            "base_url": "https://store.example",
            "root": "raw",
            "external_ref_scheme": "tiled-node-path",
        },
    }
)

AN_ENDING = datetime(2026, 9, 20, 11, 30, tzinfo=UTC)


def uid_of(scenario: str) -> str:
    start = next(doc for name, doc in raw_deliveries(scenario) if name == "start")
    return str(start["uid"])


def a_session_with_store(store: Store, **answers: list[Answer]) -> tuple[Session, Routed]:
    routed = Routed(
        report=answers.get("report") or [Answer(204)],
        register=answers.get("register") or [Answer(201, {"dataset_id": str(A_DATASET)})],
    )
    return Session(KeeperClient(routed, STORE_CONFIG), STORE_CONFIG, store), routed


def session_with_store(store: Store, **answers: list[Answer]) -> tuple[Handle, Routed]:
    """The same wiring as `session_over`, with the dataset leg switched on."""
    session, routed = a_session_with_store(store, **answers)
    return documents_into(session), routed


def store_holding(scenario: str, *, occurred_at: datetime | None = AN_ENDING) -> Store:
    uid = uid_of(scenario)
    return Store({uid: Location(path=f"raw/{uid}", occurred_at=occurred_at)})


def test_a_session_with_no_store_never_asks_one_and_reports_the_relay() -> None:
    """The default deployment, unchanged by the leg existing."""
    handle, routed = session_over()
    outcomes = drive("completes", handle)

    assert isinstance(outcomes[-1], Relayed)
    assert not routed.calls("POST", containing="/datasets")


def test_an_ending_registers_what_the_store_holds_and_reports_it_kept() -> None:
    store = store_holding("completes")
    handle, routed = session_with_store(store)

    outcomes = drive("completes", handle)

    ending = outcomes[-1]
    assert isinstance(ending, Kept)
    assert ending.dataset_id == A_DATASET
    assert ending.external_ref_value == f"raw/{uid_of('completes')}"
    assert ending.reported == "Completed"
    assert (ending.execution_id, ending.step_id) == (AN_EXECUTION, A_STEP)
    assert store.asked == [uid_of("completes")]
    assert len(routed.calls("POST", containing="/datasets")) == 1


def test_the_store_is_asked_by_the_engines_own_name_for_the_run() -> None:
    """A store watching an engine files under the engine's names, so the
    reference that travels on every report is what it is asked about."""
    store = store_holding("completes")
    handle, _ = session_with_store(store)

    drive("completes", handle)

    assert store.asked == [uid_of("completes")]


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

    assert [type(o).__name__ for o in outcomes if isinstance(o, (Relayed, Kept))] == [
        "Relayed",
        "Relayed",
        "Relayed",
        "Kept",
    ]
    assert len(routed.calls("POST", containing="/datasets")) == 1


def test_the_registration_names_the_step_the_reports_named() -> None:
    handle, routed = session_with_store(store_holding("completes"))

    drive("completes", handle)

    sent = routed.calls("POST", containing="/datasets")[0]
    assert sent.json == {
        "execution_id": str(AN_EXECUTION),
        "step_id": str(A_STEP),
        "external_ref": {
            "scheme": "tiled-node-path",
            "value": f"raw/{uid_of('completes')}",
        },
        "occurred_at": AN_ENDING.isoformat(),
    }


def test_the_registration_is_keyed_on_the_address_rather_than_the_step() -> None:
    """Two datasets from one acquisition would otherwise share a key, and
    the second would come back holding the first one's id."""
    handle, routed = session_with_store(store_holding("completes"))

    drive("completes", handle)

    sent = routed.calls("POST", containing="/datasets")[0]
    assert sent.headers is not None
    key = sent.headers["Idempotency-Key"]
    assert key == f"register-dataset:raw/{uid_of('completes')}"
    assert str(A_STEP) not in key


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


def test_aroc_refusing_the_registration_is_held_after_the_report_landed() -> None:
    """The cost of one outcome per intent, pinned rather than left to be
    discovered: the report landed and the summary will not say so."""
    handle, routed = session_with_store(
        store_holding("completes"), register=[Answer(403, text="not permitted")]
    )

    outcomes = drive("completes", handle)

    ending = outcomes[-1]
    assert isinstance(ending, Held)
    assert not [o for o in outcomes if isinstance(o, Relayed) and o.reported == "Completed"]
    assert len(routed.calls("POST", containing="/run")) == 2


def test_a_redelivered_ending_still_registers_the_dataset() -> None:
    """The first delivery may have recorded the ending and died before the
    data. The retry key makes asking again free."""
    handle, routed = session_with_store(
        store_holding("completes"),
        report=[Answer(204), Answer(409, text="has Completed from its engine")],
    )

    outcomes = drive("completes", handle)

    assert isinstance(outcomes[-1], Kept)
    assert len(routed.calls("POST", containing="/datasets")) == 1


def test_a_redelivered_ending_the_store_lost_reports_the_decline_it_got() -> None:
    """With nothing to register, the 409 is still the answer worth giving."""
    handle, _ = session_with_store(
        Store(), report=[Answer(204), Answer(409, text="has Completed from its engine")]
    )

    outcomes = drive("completes", handle)

    assert isinstance(outcomes[-1], Held)


def test_a_store_lookup_without_a_store_table_is_refused_at_construction() -> None:
    """The two halves of the configuration cannot disagree, because one of
    them carries the scheme the other's addresses belong to."""
    with pytest.raises(ValueError, match="store"):
        Session(KeeperClient(Routed(), CONFIG), CONFIG, Store())


def a_found_dataset(step_id: UUID = A_STEP) -> RegisterDataset:
    return RegisterDataset(
        execution_id=AN_EXECUTION,
        step_id=step_id,
        external_ref_value="raw/r1",
        occurred_at=AN_ENDING,
        origin="a sweep",
    )


def test_a_dataset_found_on_its_own_is_filed_against_the_step_it_names() -> None:
    """The slow path, and the reason `RegisterDataset` is in `intents`.

    Nothing here saw a document. Something swept a store, found data, and
    said so, naming the acquisition it belongs to, and the session filed
    it exactly as the ending document's path would have.
    """
    session, routed = a_session_with_store(store_holding("completes"))

    outcome = session.act(a_found_dataset())

    assert outcome == Kept(AN_EXECUTION, A_STEP, None, A_DATASET, "raw/r1")
    assert routed.calls("POST", containing="/datasets")


def test_a_dataset_found_on_its_own_carries_no_report() -> None:
    """What separates the two paths in a log: one says a run just ended,
    the other says somebody found data for a run that ended earlier."""
    session, _ = a_session_with_store(store_holding("completes"))

    found = session.act(a_found_dataset())
    fast = drive("completes", documents_into(a_session_with_store(store_holding("completes"))[0]))

    assert isinstance(found, Kept) and found.reported is None
    assert isinstance(fast[-1], Kept) and fast[-1].reported == "Completed"


def test_a_dataset_found_on_its_own_resolves_nothing() -> None:
    """The lookup the slow path used to depend on entirely is gone. A
    caller that cannot name the acquisition has nothing to file against,
    so it names one, and this asks AROC nothing before posting."""
    session, routed = a_session_with_store(store_holding("completes"))

    session.act(a_found_dataset())

    assert routed.calls("GET") == []
    assert len(routed.calls("POST")) == 1


def test_both_ways_in_send_the_same_request() -> None:
    """The point of the symmetry. Whatever found the data, AROC is asked
    the same thing, with the same key, so the two paths cannot make two
    records of one body of data."""
    uid = uid_of("completes")
    fast_session, fast_routed = a_session_with_store(store_holding("completes"))
    drive("completes", documents_into(fast_session))

    slow_session, slow_routed = a_session_with_store(store_holding("completes"))
    slow_session.act(
        RegisterDataset(
            execution_id=AN_EXECUTION,
            step_id=A_STEP,
            external_ref_value=f"raw/{uid}",
            occurred_at=AN_ENDING,
            origin="a sweep",
        )
    )

    fast = fast_routed.calls("POST", containing="/datasets")[0]
    slow = slow_routed.calls("POST", containing="/datasets")[0]
    assert fast.json == slow.json
    assert (fast.headers or {})["Idempotency-Key"] == (slow.headers or {})["Idempotency-Key"]
