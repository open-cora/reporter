"""The entrypoint's own decisions, which are the ones a run turns on.

Whether it refuses to start, what it counts, and what it exits with. The
path in between is covered by the session and relay suites; what is left
here is the wiring and the two ways a run can be over before it begins.
"""

from collections.abc import Iterator
from gc import collect
from pathlib import Path
from signal import SIGTERM, getsignal, signal
from uuid import UUID, uuid4
from weakref import ref

import pytest

from reporter.__main__ import (
    Tally,
    documents_into,
    drive,
    main,
    plans_aroc_does_not_hold,
    stop_on_termination,
)
from reporter.client import ArocClient
from reporter.config import ReporterConfig, from_mapping
from reporter.outcomes import Held, Moved, Outcome, Recorded, Skipped, Unchanged
from reporter.relay import Relay
from reporter.session import Session
from reporter.sources import DecodeError, Delivery
from tests._fakes import Answer, Routed

A_PLAN = UUID("01a0ba64-8f95-7ad1-a7a7-44124ff3afd5")
A_RUN = UUID("01a0ba65-df83-7501-aa5d-3e2318ef956c")
CAPTURED = Path(__file__).parent / "documents.json"


def a_config(**plans: str) -> ReporterConfig:
    return from_mapping(
        {
            "aroc": {
                "base_url": "https://aroc.example",
                "token": "a-token",
                "external_ref_scheme": "engine-run-uid",
            },
            "plans": plans or {"count": str(A_PLAN)},
        }
    )


def test_a_plan_aroc_does_not_hold_is_named_before_anything_is_sent() -> None:
    """The check that turns a typo in the plan map into a message at
    startup rather than a 404 at whatever hour that plan first runs."""
    config = a_config(count=str(A_PLAN), scan=str(uuid4()))
    routed = Routed(report=[], move=[], find=[Answer(200, {}), Answer(404, text="not found")])

    missing = plans_aroc_does_not_hold(ArocClient(routed, config), config)

    assert missing == ["scan"]


def test_every_plan_present_leaves_nothing_to_name() -> None:
    config = a_config()
    routed = Routed(report=[], move=[], find=[Answer(200, {})])

    assert plans_aroc_does_not_hold(ArocClient(routed, config), config) == []


def tallied(*outcomes: Outcome) -> int:
    tally = Tally()
    for outcome in outcomes:
        tally.record(outcome)
    return tally.report()


def test_a_run_with_nothing_held_succeeds() -> None:
    """The other four outcomes are the reporter working, including
    Unchanged, which is what replaying documents AROC has seen looks like."""
    assert (
        tallied(
            Recorded(A_RUN, "r1"),
            Moved(A_RUN, "complete"),
            Unchanged(A_RUN, "complete", "already Completed"),
            Skipped("a descriptor"),
        )
        == 0
    )


def test_a_run_holding_anything_fails() -> None:
    assert tallied(Recorded(A_RUN, "r1"), Held("no plan configured", "start")) == 1


def test_an_empty_run_succeeds() -> None:
    """Nothing to run is not a failure, and a non-zero here would make an
    empty capture look like a broken reporter."""
    assert tallied() == 0


def test_a_held_outcome_is_reported_when_it_happens(capsys: pytest.CaptureFixture[str]) -> None:
    """A subscription runs for as long as the engine does, so an alert it
    keeps until shutdown is an alert nobody reads."""
    tally = Tally()
    tally.record(Held("no plan configured for 'scan'", "start"))

    assert "no plan configured for 'scan'" in capsys.readouterr().err


def test_a_tally_lets_go_of_every_outcome_it_counts() -> None:
    """The reason this is a counter and not a list. A subscription runs for
    as long as the engine does, and a tally that held what it counted would
    be a week of documents in memory with a summary attached."""
    tally = Tally()
    outcome = Skipped("a descriptor")
    afterwards = ref(outcome)

    tally.record(outcome)
    del outcome
    collect()

    assert tally.report() == 0
    assert afterwards() is None, "The tally is still holding an outcome it counted."


def test_a_missing_configuration_file_stops_before_any_call(tmp_path: Path) -> None:
    """Exit 2 rather than 1: nothing was attempted, so this is a usage
    problem and not a run that went wrong."""
    code = main(["--config", str(tmp_path / "absent.toml"), "--replay", str(CAPTURED)])

    assert code == 2


def test_a_malformed_configuration_stops_before_any_call(tmp_path: Path) -> None:
    path = tmp_path / "reporter.toml"
    path.write_text('[aroc]\nbase_url = "not-a-url"\n', encoding="utf-8")

    assert main(["--config", str(path), "--replay", str(CAPTURED)]) == 2


def test_a_run_needs_a_configuration_and_a_source() -> None:
    """Argparse exits rather than returning, and that is the right shape for
    a usage error. Pinned so a refactor to optional arguments is deliberate."""
    with pytest.raises(SystemExit):
        main([])


def test_a_source_is_one_or_the_other_and_never_both(tmp_path: Path) -> None:
    """Two sources would mean two streams into one session, which is not a
    thing this can do and not a thing anybody means."""
    with pytest.raises(SystemExit):
        main(
            [
                "--config",
                str(tmp_path / "absent.toml"),
                "--replay",
                str(CAPTURED),
                "--subscribe",
                "tcp://127.0.0.1:5568",
            ]
        )


def test_a_prefix_without_a_subscription_is_refused(tmp_path: Path) -> None:
    """It selects among publishers, so on a replay it would silently do
    nothing, which is the failure mode worth refusing."""
    with pytest.raises(SystemExit):
        main(
            [
                "--config",
                str(tmp_path / "absent.toml"),
                "--replay",
                str(CAPTURED),
                "--prefix",
                "beam",
            ]
        )


def test_a_service_managers_stop_signal_becomes_an_interrupt() -> None:
    """SIGTERM is how a daemon is stopped, and the default for it skips the
    one shutdown where the relay drains what it is still holding."""
    was = getsignal(SIGTERM)
    try:
        stop_on_termination()
        installed = getsignal(SIGTERM)
        assert callable(installed)
        with pytest.raises(KeyboardInterrupt):
            installed(SIGTERM, None)
    finally:
        signal(SIGTERM, was)


def an_idle_relay() -> Relay:
    """A relay that is never started, so `submit` only queues.

    Enough for the loop below, which is about how a stream ends rather
    than about what happens to the documents in it.
    """
    config = a_config()
    handle = documents_into(Session(ArocClient(Routed(report=[], move=[]), config), config))
    return Relay(handle, lambda _: None)


def unreadable() -> Iterator[Delivery]:
    yield ("start", {"uid": "r1"})
    raise DecodeError("the payload of a 'stop' frame is not msgpack")


def test_a_stream_this_cannot_read_ends_the_run_and_says_why() -> None:
    """One frame it cannot decode means every frame, because a publisher
    encodes them all the same way. Carrying on would drop every run on the
    stream while looking like a reporter that was working."""
    assert drive(unreadable(), an_idle_relay()) == "the payload of a 'stop' frame is not msgpack"


def test_a_stream_that_simply_ends_is_not_a_problem() -> None:
    assert drive(iter([]), an_idle_relay()) is None
