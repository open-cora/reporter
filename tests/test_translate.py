"""The translation, against documents a real engine actually emitted.

`documents.json` is captured output, seven scenarios driven through a real
engine on purpose: every ending, both interruptions, a plan that raises,
and one plan with real arguments. The spike that captured it checked its
findings by printing a table and reading it. Here they are assertions, so
a change that breaks one fails a run instead of changing a report nobody
re-reads.

Each scenario also carries `expected_aroc_status`, which is the status the
engine's own transitions say the run reached. Checking the last intent
against it is what ties this file to the engine's behaviour rather than to
a prior reading of it.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from reporter.intents import Ignored, Intent, ReportRun, Transition, Unmappable
from reporter.translate import (
    ENDING_BY_EXIT_STATUS,
    Translator,
    engine_instant,
)

CAPTURED = Path(__file__).parent / "documents.json"

STATUS_BY_ENDING = {
    "complete": "Completed",
    "abort": "Aborted",
    "fail": "Failed",
}
"""The ending verbs onto the status AROC's fold produces for each.

Declared here rather than imported, because importing it would mean this
package depends on the model it reports to and the whole point is that it
does not. A drift between the two is caught by the contract tier in
apps/api, which exercises the real deciders.
"""


Document = dict[str, Any]
Delivery = tuple[str, Document]
"""One document as the stream delivered it: its type name, and the document.

A pair rather than the capture's own `{"name": ..., "doc": ...}` shape,
because the fixture is untyped JSON and coercing once at the edge keeps
every test below typed.
"""


def captured() -> dict[str, Any]:
    return json.loads(CAPTURED.read_text(encoding="utf-8"))


def scenarios() -> list[str]:
    return sorted(captured())


def deliveries(scenario: str) -> list[Delivery]:
    """One scenario's documents, in the order the engine emitted them."""
    entries: list[dict[str, Any]] = captured()[scenario]["documents"]
    return [(str(entry["name"]), dict(entry["doc"])) for entry in entries]


def translate_all(scenario: str) -> list[Intent]:
    """Feed one scenario's documents to a fresh translator, in order."""
    translator = Translator()
    return [translator.feed(name, document) for name, document in deliveries(scenario)]


def test_the_capture_holds_scenarios_to_range_over() -> None:
    """Guard the enumeration: an empty file makes every check below vacuous."""
    assert scenarios(), f"{CAPTURED} carries no scenarios, so nothing is asserted."


@pytest.mark.parametrize("scenario", scenarios())
def test_a_scenario_opens_with_a_run_to_report(scenario: str) -> None:
    intents = translate_all(scenario)

    assert isinstance(intents[0], ReportRun), (
        f"{scenario} does not begin with a run to report. Every capture opens "
        f"with a start document, so this is the translator, not the data: {intents[0]}"
    )


UNPREDICTED = "unknown"
"""What the capture records for a scenario whose ending nobody could predict.

One of the seven is the hard stop, and the reason it carries no expected
status is the trap in `ENDING_BY_EXIT_STATUS`: asking an engine to stop
and a plan finishing both record `success`, while the hard stop records
`abort`. The spike drove it to find out rather than to confirm, and left
the answer out of the fixture so that reading it back would not look like
a prediction. Asserting one here would invent the certainty it declined.
"""


@pytest.mark.parametrize("scenario", scenarios())
def test_a_scenario_ends_where_the_engine_says_it_ended(scenario: str) -> None:
    """The spike's printed agreement table, as a failure rather than a column."""
    recorded = captured()[scenario]
    intents = translate_all(scenario)
    endings = [i for i in intents if isinstance(i, Transition) and i.verb in STATUS_BY_ENDING]

    assert len(endings) == 1, f"{scenario} produced {len(endings)} endings, not one."
    if recorded["expected_aroc_status"] == UNPREDICTED:
        pytest.skip(f"{scenario} records no expected status; see UNPREDICTED")
    assert STATUS_BY_ENDING[endings[0].verb] == recorded["expected_aroc_status"]


@pytest.mark.parametrize("scenario", scenarios())
def test_a_scenario_translates_every_document_it_carries(scenario: str) -> None:
    """No document falls through to something the caller cannot act on."""
    intents = translate_all(scenario)

    assert len(intents) == len(deliveries(scenario))
    unmappable = [i for i in intents if isinstance(i, Unmappable)]
    assert not unmappable, (
        f"{scenario} carries documents this translator cannot map, which means "
        f"a real run would be reported wrong or not at all: {unmappable}"
    )


def test_an_interruption_is_attributed_through_its_descriptor() -> None:
    """The hop the spike skipped, which is why it could not interleave.

    An event names a descriptor and a descriptor names the run, so
    attribution needs both documents and no memory of "the run we are
    walking".
    """
    intents = translate_all("pause_resume_complete")
    moves = [i.verb for i in intents if isinstance(i, Transition)]

    assert moves == ["pause", "resume", "complete"]


def test_two_runs_interleaved_keep_their_own_interruptions() -> None:
    """The case a current-run pointer gets wrong, which a live stream produces.

    Built by relabelling one captured scenario, so both halves are real
    documents rather than invented ones, and the uids differ because the
    engine mints one per run and per descriptor.
    """
    first = deliveries("pause_resume_complete")
    second = [(name, _suffixed(document)) for name, document in first]

    translator = Translator()
    for name, document in first[:2] + second[:2]:
        translator.feed(name, document)

    from_first = translator.feed(*first[2])
    from_second = translator.feed(*second[2])

    assert isinstance(from_first, Transition)
    assert isinstance(from_second, Transition)
    assert from_first.run_uid != from_second.run_uid
    assert from_second.run_uid == from_first.run_uid + "-b"


def _suffixed(document: Document) -> Document:
    """The same document belonging to a second run, by suffixing every uid."""
    copy = dict(document)
    for key in ("uid", "run_start", "descriptor"):
        if isinstance(copy.get(key), str):
            copy[key] = f"{copy[key]}-b"
    return copy


def test_a_descriptor_is_ignored_rather_than_reported() -> None:
    intents = translate_all("completes")
    descriptors = [
        intent
        for (name, _), intent in zip(deliveries("completes"), intents, strict=True)
        if name == "descriptor"
    ]

    assert descriptors
    assert all(isinstance(intent, Ignored) for intent in descriptors)


def test_an_event_carrying_no_interruption_is_a_reading() -> None:
    translator = Translator()
    translator.feed("descriptor", {"uid": "d1", "run_start": "r1"})

    intent = translator.feed("event", {"descriptor": "d1", "data": {"det": 1.0}, "seq_num": 1})

    assert isinstance(intent, Ignored)


def test_an_unknown_document_type_is_ignored_and_says_which() -> None:
    """A stream carries several document types that say nothing about a run.

    Refusing them would report every reading as a problem. Naming the type
    in the reason keeps them countable without making them events.
    """
    intent = Translator().feed("stream_datum", {"uid": "x"})

    assert isinstance(intent, Ignored)
    assert "stream_datum" in intent.reason


def test_an_unknown_exit_status_is_unmappable_and_not_ignored() -> None:
    """The distinction the spike collapsed, and the reason for two types.

    A fourth ending, or a typo here, must not read the same as a document
    that was never going to produce anything.
    """
    intent = Translator().feed("stop", {"run_start": "r1", "exit_status": "vaporised"})

    assert isinstance(intent, Unmappable)
    assert "vaporised" in intent.reason


def test_an_interruption_for_a_run_never_introduced_is_unmappable() -> None:
    """What a reporter joining mid-run sees, and must not report as a pause
    on whichever run it happens to know about."""
    intent = Translator().feed("event", {"descriptor": "unseen", "data": {"interruption": "pause"}})

    assert isinstance(intent, Unmappable)


def test_a_run_is_forgotten_once_it_has_ended() -> None:
    """The map tracks live runs, so a never-ending stream does not leak one."""
    translator = Translator()
    translator.feed("descriptor", {"uid": "d1", "run_start": "r1"})
    translator.feed("stop", {"run_start": "r1", "exit_status": "success"})

    after = translator.feed("event", {"descriptor": "d1", "data": {"interruption": "pause"}})

    assert isinstance(after, Unmappable)


def test_every_ending_the_engine_can_record_maps_to_a_verb() -> None:
    """Guard the table: a status missing from it fails a real run silently."""
    assert set(ENDING_BY_EXIT_STATUS) == {"success", "abort", "fail"}
    assert set(ENDING_BY_EXIT_STATUS.values()) == set(STATUS_BY_ENDING)


def test_a_start_with_no_arguments_reports_empty_parameters() -> None:
    """Six of the seven captures have no plan_args, so this is the common case."""
    intents = translate_all("completes")
    first = intents[0]

    assert isinstance(first, ReportRun)
    assert first.parameters == {}
    assert first.dropped == ()


def test_the_real_plan_takes_its_arguments_and_its_device_names() -> None:
    """The composition finding: scalars from the call, device names from
    the key that holds names rather than the key that holds reprs."""
    intents = translate_all("real_plan")
    first = intents[0]

    assert isinstance(first, ReportRun)
    assert first.plan_name == "count"
    assert first.parameters["num"] == 2
    assert first.parameters["detectors"] == ["det"]


def test_a_device_repr_in_the_arguments_is_dropped_and_named() -> None:
    """Dropping it is right; dropping it silently is not.

    The argument list holds whole object dumps with configuration inline.
    The clean name is on a different key, and what was left behind travels
    with the intent so a sender can say so.
    """
    intent = Translator().feed(
        "start",
        {
            "uid": "r1",
            "plan_name": "count",
            "plan_args": {"detectors": ["SynGauss(prefix='', name='det')"], "num": 2},
            "detectors": ["det"],
        },
    )

    assert isinstance(intent, ReportRun)
    assert intent.dropped == ("detectors",)
    assert intent.parameters == {"num": 2, "detectors": ["det"]}


def test_a_documents_time_becomes_an_instant_with_an_offset() -> None:
    """AROC refuses a timestamp with no offset, and the engine sends seconds."""
    assert engine_instant({"time": 1789812131.0}) == datetime(2026, 9, 19, 10, 2, 11, tzinfo=UTC)


def test_a_document_with_no_usable_time_yields_none() -> None:
    """AROC then stamps the moment it was told, which is the honest record."""
    assert engine_instant({}) is None
    assert engine_instant({"time": None}) is None
    assert engine_instant({"time": "yesterday"}) is None


def test_every_captured_document_that_moves_a_run_carries_a_time() -> None:
    """If this fails, a real run would be recorded at the moment it was
    reported rather than the moment it happened."""
    undated = [
        (scenario, name)
        for scenario in scenarios()
        for (name, _), intent in zip(deliveries(scenario), translate_all(scenario), strict=True)
        if isinstance(intent, (ReportRun, Transition)) and intent.occurred_at is None
    ]

    assert not undated, f"Documents that move a run and carry no time: {undated}"
