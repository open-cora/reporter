"""The relay hands documents over and never makes the engine wait.

Threaded, so every test here drives it to a known point and stops it:
`stop` drains, which is what makes the assertions deterministic rather
than timed.
"""

import threading
from typing import Any
from uuid import UUID

import pytest

from reporter.client import ArocClient
from reporter.config import from_mapping
from reporter.outcomes import Held, Outcome, Recorded, Skipped
from reporter.relay import DEFAULT_RETRY_DELAYS, Relay
from reporter.session import Session
from reporter.wire import documents_into
from tests._fakes import Answer, Routed

A_PLAN = UUID("01a0ba64-8f95-7ad1-a7a7-44124ff3afd5")
A_RUN = UUID("01a0ba65-df83-7501-aa5d-3e2318ef956c")

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

A_START = {"uid": "r1", "plan_name": "count", "time": 1.0}


def relay_over(
    *answers: Answer, retry_delays: tuple[float, ...] = (), capacity: int = 100
) -> tuple[Relay, list[Outcome], Routed]:
    """A relay whose retries take no time, so the tests do not either."""
    routed = Routed(report=list(answers) or [Answer(201, {"run_id": str(A_RUN)})], move=[])
    handle = documents_into(Session(ArocClient(routed, CONFIG), CONFIG))
    seen: list[Outcome] = []
    return (
        Relay(handle, seen.append, capacity=capacity, retry_delays=retry_delays),
        seen,
        routed,
    )


def test_a_submitted_document_is_handled_on_the_relays_own_thread() -> None:
    relay, seen, _ = relay_over()
    relay.start()
    relay.submit("start", A_START)
    relay.stop(timeout=5)

    assert [type(o).__name__ for o in seen] == ["Recorded"]


def test_submitting_does_not_wait_for_the_previous_document() -> None:
    """The property the whole module exists for: the engine's thread hands
    over and carries on while AROC is still being talked to.

    The handler is held open, so a `submit` that waited on the worker would
    not return. Done on a thread with a bounded wait, because a regression
    here should fail in five seconds rather than hang a CI run.
    """
    started = threading.Event()
    release = threading.Event()
    returned = threading.Event()

    def block(_: Outcome) -> None:
        started.set()
        release.wait(5)

    routed = Routed(report=[Answer(201, {"run_id": str(A_RUN)})], move=[])
    handle = documents_into(Session(ArocClient(routed, CONFIG), CONFIG))
    relay = Relay(handle, block, retry_delays=())
    relay.start()
    relay.submit("start", A_START)
    assert started.wait(5), "The worker never picked the first document up."

    def submit_second() -> None:
        relay.submit("start", dict(A_START, uid="r2"))
        returned.set()

    threading.Thread(target=submit_second, daemon=True).start()
    handed_over = returned.wait(5)

    release.set()
    relay.stop(timeout=5)
    assert handed_over, "submit waited for the worker, which is a stalled scan."


def test_stopping_finishes_what_is_already_queued() -> None:
    """A clean shutdown is the one moment this reporter can avoid losing
    documents it already holds."""
    relay, seen, _ = relay_over(Answer(201, {"run_id": str(A_RUN)}))
    relay.start()
    for index in range(5):
        relay.submit("start", dict(A_START, uid=f"r{index}"))
    relay.stop(timeout=5)

    assert len(seen) == 5
    assert all(isinstance(o, Recorded) for o in seen)


def test_a_full_queue_refuses_rather_than_waiting() -> None:
    """An unbounded queue turns an AROC outage into memory exhaustion on the
    engine's own host, which is worse than what it was protecting against."""
    relay, seen, _ = relay_over(capacity=1)
    # Not started: nothing drains, so the queue fills and stays full.
    assert relay.submit("start", A_START) is True
    assert relay.submit("start", dict(A_START, uid="r2")) is False

    assert isinstance(seen[0], Held)
    assert "full" in seen[0].reason


def test_a_dropped_document_is_reported_rather_than_lost_quietly() -> None:
    relay, seen, _ = relay_over(capacity=1)
    relay.submit("start", A_START)
    relay.submit("descriptor", {"uid": "d1", "run_start": "r1"})

    assert [o.origin for o in seen if isinstance(o, Held)] == ["descriptor"]


def test_a_refusal_worth_waiting_on_is_retried() -> None:
    """The distinction `Session.handle` draws, acted on. A 503 then a 201
    is one Recorded, not one Held."""
    relay, seen, routed = relay_over(
        Answer(503, text="unavailable"),
        Answer(201, {"run_id": str(A_RUN)}),
        retry_delays=(0.0,),
    )
    relay.start()
    relay.submit("start", A_START)
    relay.stop(timeout=5)

    assert [type(o).__name__ for o in seen] == ["Recorded"]
    assert len(routed.calls("POST")) == 2


def test_retrying_stops_and_says_so_rather_than_blocking_the_queue() -> None:
    """A worker retrying one document forever is a worker not draining the
    ones behind it, so an outage would cost every later document too."""
    relay, seen, routed = relay_over(Answer(503, text="unavailable"), retry_delays=(0.0, 0.0))
    relay.start()
    relay.submit("start", A_START)
    relay.stop(timeout=5)

    assert isinstance(seen[0], Held)
    assert "gave up after 3 attempts" in seen[0].reason
    assert len(routed.calls("POST")) == 3


def test_a_request_that_never_arrived_is_retried_like_a_refusal() -> None:
    """A dropped connection and a 503 want the same handling, and only one
    of them arrives as a status."""
    attempts: list[int] = []

    class Failing:
        def get(self, url: str, **_: Any) -> Answer:
            raise AssertionError("not used")

        def post(self, url: str, **_: Any) -> Answer:
            attempts.append(1)
            if len(attempts) < 2:
                raise OSError("connection reset")
            return Answer(201, {"run_id": str(A_RUN)})

    session = Session(ArocClient(Failing(), CONFIG), CONFIG)
    seen: list[Outcome] = []
    relay = Relay(documents_into(session), seen.append, retry_delays=(0.0,))
    relay.start()
    relay.submit("start", A_START)
    relay.stop(timeout=5)

    assert [type(o).__name__ for o in seen] == ["Recorded"]
    assert len(attempts) == 2


def test_a_document_that_needs_no_call_still_reports_an_outcome() -> None:
    """A caller counting outcomes should see every document, including the
    ones that were never going to produce a request."""
    relay, seen, routed = relay_over()
    relay.start()
    relay.submit("descriptor", {"uid": "d1", "run_start": "r1"})
    relay.stop(timeout=5)

    assert isinstance(seen[0], Skipped)
    assert routed.sent == []


def test_stopping_a_relay_that_never_started_is_harmless() -> None:
    relay, _, _ = relay_over()
    relay.stop(timeout=1)


def test_starting_twice_is_refused_rather_than_silently_ignored() -> None:
    """Two workers on one queue would interleave documents from one run,
    which is the one ordering this reporter needs."""
    relay, _, _ = relay_over()
    relay.start()
    try:
        with pytest.raises(RuntimeError):
            relay.start()
    finally:
        relay.stop(timeout=5)


def test_the_default_retry_policy_backs_off_rather_than_hammering() -> None:
    """Guard the constant: a policy of zeros would retry three times inside
    a millisecond and call the outage permanent."""
    assert list(DEFAULT_RETRY_DELAYS) == sorted(DEFAULT_RETRY_DELAYS)
    assert DEFAULT_RETRY_DELAYS[0] > 0
    assert sum(DEFAULT_RETRY_DELAYS) >= 10


def test_the_queue_is_bounded_by_the_capacity_it_was_given() -> None:
    relay, _, _ = relay_over(capacity=2)
    assert relay.submit("start", A_START)
    assert relay.submit("start", dict(A_START, uid="r2"))
    assert not relay.submit("start", dict(A_START, uid="r3"))
