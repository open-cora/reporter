"""The entrypoint's own decisions, which are the ones a run turns on.

Whether it refuses to start, what it counts, and what it exits with. The
path in between is covered by the session and relay suites; what is left
here is the wiring and the two ways a run can be over before it begins.
"""

import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from reporter.__main__ import main, plans_aroc_does_not_hold, summarise
from reporter.client import ArocClient
from reporter.config import ReporterConfig, from_mapping
from reporter.outcomes import Held, Moved, Recorded, Skipped, Unchanged
from reporter.sources import from_capture
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


def test_the_capture_flattens_into_one_stream_in_order() -> None:
    """A reporter sees one stream. The capture groups by scenario because it
    was written to compare them."""
    stream = list(from_capture(CAPTURED))

    assert stream
    assert all(isinstance(name, str) and isinstance(doc, dict) for name, doc in stream)
    assert stream[0][0] == "start"


def test_every_captured_document_survives_the_flattening() -> None:
    """Off-by-one here silently drops a run, and nothing downstream notices."""
    captured = json.loads(CAPTURED.read_text(encoding="utf-8"))
    expected = sum(len(scenario["documents"]) for scenario in captured.values())

    assert len(list(from_capture(CAPTURED))) == expected


def test_a_plan_aroc_does_not_hold_is_named_before_anything_is_sent() -> None:
    """The check that turns a typo in the plan map into a message at
    startup rather than a 404 at whatever hour that plan first runs."""
    config = a_config(count=str(A_PLAN), scan=str(uuid4()))
    routed = Routed(report=[], move=[], find=[Answer(200, {}), Answer(404, text="not found")])

    missing = plans_aroc_does_not_hold(ArocClient(routed, config), config)

    assert missing == ["scan"]


def test_every_plan_present_leaves_nothing_tosummarise() -> None:
    config = a_config()
    routed = Routed(report=[], move=[], find=[Answer(200, {})])

    assert plans_aroc_does_not_hold(ArocClient(routed, config), config) == []


def test_a_run_with_nothing_held_succeeds() -> None:
    """The other four outcomes are the reporter working, including
    Unchanged, which is what replaying documents AROC has seen looks like."""
    assert (
        summarise(
            [
                Recorded(A_RUN, "r1"),
                Moved(A_RUN, "complete"),
                Unchanged(A_RUN, "complete", "already Completed"),
                Skipped("a descriptor"),
            ]
        )
        == 0
    )


def test_a_run_holding_anything_fails() -> None:
    assert summarise([Recorded(A_RUN, "r1"), Held("no plan configured", "start")]) == 1


def test_an_empty_run_succeeds() -> None:
    """Nothing to replay is not a failure, and a non-zero here would make
    an empty capture look like a broken reporter."""
    assert summarise([]) == 0


def test_a_missing_configuration_file_stops_before_any_call(tmp_path: Path) -> None:
    """Exit 2 rather than 1: nothing was attempted, so this is a usage
    problem and not a run that went wrong."""
    code = main(["--config", str(tmp_path / "absent.toml"), "--replay", str(CAPTURED)])

    assert code == 2


def test_a_malformed_configuration_stops_before_any_call(tmp_path: Path) -> None:
    path = tmp_path / "reporter.toml"
    path.write_text('[aroc]\nbase_url = "not-a-url"\n', encoding="utf-8")

    assert main(["--config", str(path), "--replay", str(CAPTURED)]) == 2


def test_both_paths_are_required() -> None:
    """Argparse exits rather than returning, and that is the right shape for
    a usage error. Pinned so a refactor to optional arguments is deliberate."""
    with pytest.raises(SystemExit):
        main([])
