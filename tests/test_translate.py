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

## The capture is a hand-run scan, and is used both ways

Nothing in it carries an AROC reference, because it was taken by driving
an engine directly and no conductor was involved. That is not a gap in
the fixture: it is exactly what work this system did not dispatch looks
like, so the untouched capture is what proves the quiet path.

`dispatched` puts the two keys onto each scenario's start, which is what
a driver will do, and every other check below runs against that. The
documents underneath are still the engine's own; the only thing invented
is the pair of ids, which is the only part a driver invents too.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from reporter.intents import Ignored, Intent, RegisterDataset, ReportStepRun, Unmappable
from reporter.translate import (
    AROC_METADATA_KEYS,
    ENDING_BY_EXIT_STATUS,
    Translator,
    aroc_reference,
    engine_instant,
)

CAPTURED = Path(__file__).parent / "documents.json"

_EXECUTION_ID = UUID(int=1)
_STEP_ID = UUID(int=2)

STATUS_BY_ENDING = {
    "Completed": "Completed",
    "Aborted": "Aborted",
    "Failed": "Failed",
}
"""The ending reports onto the status AROC's fold produces for each.

Now an identity map, and kept rather than deleted because what it asserts
is that the two vocabularies agree. They did not before: this reporter
sent lowercase verbs in a path and AROC derived a status word from them,
so the mapping was real. AROC takes the word itself now, and a check that
the two still line up costs one dictionary.

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


def raw_deliveries(scenario: str) -> list[Delivery]:
    """One scenario's documents, exactly as the engine emitted them."""
    entries: list[dict[str, Any]] = captured()[scenario]["documents"]
    return [(str(entry["name"]), dict(entry["doc"])) for entry in entries]


def dispatched(
    deliveries: list[Delivery],
    *,
    execution_id: UUID = _EXECUTION_ID,
    step_id: UUID = _STEP_ID,
) -> list[Delivery]:
    """The same documents, as they arrive when AROC dispatched the work.

    Only the start is touched, because only the start carries the
    reference. That asymmetry is the reason the translator holds a map at
    all, so a helper that decorated every document would hide the thing
    most worth testing.
    """
    execution_key, step_key = AROC_METADATA_KEYS
    return [
        (name, {**document, execution_key: str(execution_id), step_key: str(step_id)})
        if name == "start"
        else (name, document)
        for name, document in deliveries
    ]


def deliveries(scenario: str) -> list[Delivery]:
    return dispatched(raw_deliveries(scenario))


def translate_all(scenario: str) -> list[Intent]:
    """Feed one scenario's documents to a fresh translator, in order."""
    translator = Translator()
    return [translator.feed(name, document) for name, document in deliveries(scenario)]


def test_the_capture_holds_scenarios_to_range_over() -> None:
    """Guard the enumeration: an empty file makes every check below vacuous."""
    assert scenarios(), f"{CAPTURED} carries no scenarios, so nothing is asserted."


@pytest.mark.parametrize("scenario", scenarios())
def test_a_scenario_opens_by_reporting_that_the_engine_started(scenario: str) -> None:
    intents = translate_all(scenario)

    assert isinstance(intents[0], ReportStepRun), (
        f"{scenario} does not begin with a report. Every capture opens "
        f"with a start document, so this is the translator, not the data: {intents[0]}"
    )
    assert intents[0].reported == "Started"


@pytest.mark.parametrize("scenario", scenarios())
def test_a_scenario_nobody_dispatched_produces_nothing_to_send(scenario: str) -> None:
    """The capture as it stands, which is what a hand-run scan looks like.

    Every document is skipped and none is an alert. A translator that
    made these `Unmappable` would fire on every document of every scan
    somebody ran at the beamline, which is the noise that teaches an
    operator to stop reading the channel.
    """
    translator = Translator()
    intents = [translator.feed(name, document) for name, document in raw_deliveries(scenario)]

    assert all(isinstance(intent, Ignored) for intent in intents), [
        intent for intent in intents if not isinstance(intent, Ignored)
    ]


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
    endings = [
        i for i in intents if isinstance(i, ReportStepRun) and i.reported in STATUS_BY_ENDING
    ]

    assert len(endings) == 1, f"{scenario} produced {len(endings)} endings, not one."
    if recorded["expected_aroc_status"] == UNPREDICTED:
        pytest.skip(f"{scenario} records no expected status; see UNPREDICTED")
    assert STATUS_BY_ENDING[endings[0].reported] == recorded["expected_aroc_status"]


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


@pytest.mark.parametrize("scenario", scenarios())
def test_every_report_in_a_scenario_names_the_step_its_start_carried(scenario: str) -> None:
    """The reference has to survive from the start to the stop.

    Only the start document carries it, so a translator that read it and
    did not keep it would report the opening and lose every later
    document of the same run.
    """
    reports = [i for i in translate_all(scenario) if isinstance(i, ReportStepRun)]

    assert len(reports) > 1, f"{scenario} has one report, so nothing is carried across."
    assert {(i.execution_id, i.step_id) for i in reports} == {(_EXECUTION_ID, _STEP_ID)}


def test_an_interruption_is_attributed_through_its_descriptor() -> None:
    """The hop the spike skipped, which is why it could not interleave.

    An event names a descriptor and a descriptor names the run, so
    attribution needs both documents and no memory of "the run we are
    walking".
    """
    intents = translate_all("pause_resume_complete")
    reports = [i.reported for i in intents if isinstance(i, ReportStepRun)]

    assert reports == ["Started", "Paused", "Resumed", "Completed"]


def test_two_runs_interleaved_keep_their_own_steps() -> None:
    """The case a current-run pointer gets wrong, which a live stream produces.

    Built by relabelling one captured scenario, so both halves are real
    documents rather than invented ones, and the uids differ because the
    engine mints one per run and per descriptor. The two runs are given
    different steps, which is what two acquisitions of one procedure
    running at once would look like.
    """
    other_step = uuid4()
    first = deliveries("pause_resume_complete")
    second = [
        (name, _suffixed(document)) for name, document in raw_deliveries("pause_resume_complete")
    ]
    second = dispatched(second, step_id=other_step)

    translator = Translator()
    for name, document in first[:2] + second[:2]:
        translator.feed(name, document)

    from_first = translator.feed(*first[2])
    from_second = translator.feed(*second[2])

    assert isinstance(from_first, ReportStepRun)
    assert isinstance(from_second, ReportStepRun)
    assert from_first.step_id == _STEP_ID
    assert from_second.step_id == other_step
    assert from_second.engine_reference == from_first.engine_reference + "-b"


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

    Checked before the reference is, which is why this passes for a run
    the translator never saw start: an ending nobody can map is a fact
    about this translator, and saying the run is unknown instead would
    send whoever reads it looking in the wrong place.
    """
    intent = Translator().feed("stop", {"run_start": "r1", "exit_status": "vaporised"})

    assert isinstance(intent, Unmappable)
    assert "vaporised" in intent.reason


def test_an_interruption_for_a_run_never_introduced_is_unmappable() -> None:
    """What a reporter joining mid-run sees, and must not report as a pause
    on whichever step it happens to know about."""
    intent = Translator().feed("event", {"descriptor": "unseen", "data": {"interruption": "pause"}})

    assert isinstance(intent, Unmappable)


def test_an_ending_for_a_dispatched_run_whose_start_was_missed_is_unmappable() -> None:
    """The cost of holding the reference in memory, made visible.

    A reporter restarted mid-scan holds no reference for a run in
    flight, and unlike the design this replaced there is no lookup that
    would recover it: AROC publishes no way to find a step by what an
    engine calls the run it opened. So the ending is lost, and it is lost
    loudly.
    """
    intent = Translator().feed("stop", {"run_start": "r1", "exit_status": "success"})

    assert isinstance(intent, Unmappable)
    assert "joined after its start" in intent.reason


def test_a_hand_run_scan_stays_quiet_after_its_start_as_well() -> None:
    """The alert this translator must not produce, over and over.

    A start with no reference is skipped, and so is everything that
    follows it. Skipping only the start would put two alerts on every
    hand-run scan, which is the noise that makes the channel worthless.
    """
    translator = Translator()
    for name, document in raw_deliveries("pause_resume_complete"):
        intent = translator.feed(name, document)
        assert isinstance(intent, Ignored), (name, intent)


def test_a_run_is_forgotten_once_it_has_ended() -> None:
    """The maps track live runs, so a never-ending stream does not leak one.

    Driven with the scenario's own descriptor rather than an invented
    one, because a descriptor this stream never carried would be
    unattributable whether or not anything was forgotten.
    """
    translator = Translator()
    for name, document in deliveries("completes"):
        translator.feed(name, document)
    descriptor = next(doc["uid"] for name, doc in deliveries("completes") if name == "descriptor")

    after = translator.feed("event", {"descriptor": descriptor, "data": {"interruption": "pause"}})

    assert isinstance(after, Unmappable)


def test_a_second_stop_for_a_forgotten_run_is_unmappable() -> None:
    """Forgetting the reference is what makes a redelivered stop visible here.

    It does not reach AROC, so AROC's own 409 never fires for it. That is
    a difference from the design this replaced, where the reference could
    be re-resolved, and it is the reason the forgetting happens after the
    intent is built rather than before.
    """
    translator = Translator()
    for name, document in deliveries("completes"):
        translator.feed(name, document)
    stop = next(document for name, document in deliveries("completes") if name == "stop")

    again = translator.feed("stop", stop)

    assert isinstance(again, Unmappable)


def test_every_ending_the_engine_can_record_maps_to_a_report() -> None:
    """Guard the table: a status missing from it fails a real run silently."""
    assert set(ENDING_BY_EXIT_STATUS) == {"success", "abort", "fail"}
    assert set(ENDING_BY_EXIT_STATUS.values()) == set(STATUS_BY_ENDING)


def test_a_start_carries_the_engines_own_id_as_the_reference() -> None:
    """AROC records it on the step, and the store is asked about it by name."""
    intents = translate_all("completes")
    first = intents[0]

    assert isinstance(first, ReportStepRun)
    assert first.engine_reference == raw_deliveries("completes")[0][1]["uid"]


def test_a_start_with_no_uid_is_unmappable_rather_than_ignored() -> None:
    """A start is the one document that must be well-formed.

    Checked before the reference, because a start with no uid is a broken
    document whatever else it carries, and calling it a hand-run scan
    would hide that.
    """
    intent = Translator().feed("start", {"plan_name": "count"})

    assert isinstance(intent, Unmappable)


def test_a_reference_that_is_not_a_pair_of_ids_reads_as_no_reference() -> None:
    """Half a reference and a malformed one both mean this is not ours.

    Quiet rather than loud, because there is no way to tell a driver that
    wrote a bad id from an unrelated engine using the same key for
    something else, and the loud reading cannot be taken back once it has
    trained somebody to ignore the channel.
    """
    execution_key, step_key = AROC_METADATA_KEYS

    assert aroc_reference({execution_key: str(uuid4())}) is None
    assert aroc_reference({execution_key: "not-an-id", step_key: str(uuid4())}) is None
    assert aroc_reference({execution_key: str(uuid4()), step_key: 7}) is None


def test_a_reference_both_keys_carry_reads_back_as_the_pair() -> None:
    execution_key, step_key = AROC_METADATA_KEYS

    found = aroc_reference({execution_key: str(_EXECUTION_ID), step_key: str(_STEP_ID)})

    assert found == (_EXECUTION_ID, _STEP_ID)


def test_the_translator_never_produces_a_dataset_registration() -> None:
    """The slow path into Custody exists and nothing engine-shaped takes it.

    A store is what knows where data landed, and this module has never
    heard of one. Pinned because `RegisterDataset` is in the intent union
    and a reader could reasonably expect a stop to produce one.
    """
    produced = [intent for scenario in scenarios() for intent in translate_all(scenario)]

    assert not [intent for intent in produced if isinstance(intent, RegisterDataset)]


def test_a_documents_time_becomes_an_instant_with_an_offset() -> None:
    """AROC refuses a timestamp with no offset, and the engine sends seconds."""
    assert engine_instant({"time": 1789812131.0}) == datetime(2026, 9, 19, 10, 2, 11, tzinfo=UTC)


def test_a_document_with_no_usable_time_yields_none() -> None:
    """AROC then stamps the moment it was told, which is the honest record."""
    assert engine_instant({}) is None
    assert engine_instant({"time": None}) is None
    assert engine_instant({"time": "yesterday"}) is None


def test_every_captured_document_that_reports_something_carries_a_time() -> None:
    """If this fails, a real run would be recorded at the moment it was
    reported rather than the moment it happened."""
    undated = [
        (scenario, name)
        for scenario in scenarios()
        for (name, _), intent in zip(deliveries(scenario), translate_all(scenario), strict=True)
        if isinstance(intent, ReportStepRun) and intent.occurred_at is None
    ]

    assert not undated, f"Documents that report something and carry no time: {undated}"
