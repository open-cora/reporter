"""Drive a real acquisition engine and record everything it emits.

Writes `tests/documents.json`, which most of this project's tests read
instead of an engine. Six scenarios against an engine with no hardware:
every document, every state transition, every interruption.

This script knows nothing about the reporter. That is what makes the
capture worth having, because a fixture recorded by the thing under test
would agree with it by construction. It began life as half of a throwaway
spike and stayed when the spike went, for the same reason: the questions
about the engine were answered by running it, and the answers are in the
file this writes.

It is not part of any test run and nothing imports it. The captures are
committed, so this is only ever run deliberately, when a newer engine is
worth re-recording against.

    make refresh-captures
"""

from __future__ import annotations

import json
import platform
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

from bluesky import RunEngine, RunEngineInterrupted
from bluesky import plan_stubs as bps
from bluesky.preprocessors import run_decorator

REPORTER = Path(__file__).resolve().parents[1]
OUT = REPORTER / "tests" / "documents.json"
"""Where the capture is written, which is the reporter's test fixture.

Re-running this overwrites what the reporter's tests assert against, which
is deliberate: a capture from a newer engine that changes an assertion is
exactly the signal worth having, and the diff is the finding.
"""


class Recorder:
    """Collects documents and state transitions from one engine.

    The document callback only appends. Anything slower would run on the
    engine's own thread and change the timing of the thing being measured,
    which is also the reason a real adapter wants a queue here rather than
    an HTTP call.
    """

    def __init__(self) -> None:
        self.documents: list[tuple[str, dict[str, Any]]] = []
        self.transitions: list[tuple[str, str]] = []

    def on_document(self, name: str, doc: dict[str, Any]) -> None:
        self.documents.append((name, doc))

    def on_state(self, new_state: str, old_state: str) -> None:
        self.transitions.append((old_state, new_state))

    def as_json(self) -> dict[str, Any]:
        return {
            "documents": [{"name": n, "doc": d} for n, d in self.documents],
            "transitions": [{"from": a, "to": b} for a, b in self.transitions],
        }


def engine() -> tuple[RunEngine, Recorder]:
    """A fresh engine with all three observation channels switched on.

    A new one per scenario, so nothing bleeds between them. All three
    channels are armed at once because which of them actually reports a
    pause is one of the questions.
    """
    run_engine = RunEngine({})
    recorder = Recorder()
    run_engine.record_interruptions = True
    run_engine.state_hook = recorder.on_state
    run_engine.subscribe(recorder.on_document)
    return run_engine, recorder


@run_decorator()
def _plain_plan():
    """Opens a run, does a little work, closes it. No detectors."""
    yield from bps.checkpoint()
    yield from bps.sleep(0.01)
    yield from bps.checkpoint()
    yield from bps.sleep(0.01)


@run_decorator()
def _pausing_plan():
    """Opens a run and pauses itself partway through.

    The pause is a message inside the plan rather than a signal or a
    second thread, which keeps every scenario deterministic and
    single-threaded: `RE(plan)` returns control at the pause and the
    caller decides what happens next.
    """
    yield from bps.checkpoint()
    yield from bps.sleep(0.01)
    yield from bps.pause()
    yield from bps.checkpoint()
    yield from bps.sleep(0.01)


@run_decorator()
def _failing_plan():
    """Opens a run and then breaks."""
    yield from bps.checkpoint()
    yield from bps.sleep(0.01)
    raise RuntimeError("the spike broke this run on purpose")


def _run_to_pause(run_engine: RunEngine, plan: Any) -> str | None:
    """Start a plan expected to pause. Returns the interruption message."""
    try:
        run_engine(plan)
    except RunEngineInterrupted as interrupted:
        return str(interrupted)
    return None


def scenario_completes() -> dict[str, Any]:
    run_engine, recorder = engine()
    run_engine(_plain_plan())
    return {"expected_aroc_status": "Completed", **recorder.as_json()}


def scenario_pause_resume_complete() -> dict[str, Any]:
    run_engine, recorder = engine()
    interruption = _run_to_pause(run_engine, _pausing_plan())
    paused_state = run_engine.state
    run_engine.resume()
    return {
        "expected_aroc_status": "Completed",
        "state_while_paused": paused_state,
        "interruption_message": interruption,
        **recorder.as_json(),
    }


def _scenario_ending_from_pause(method: str, expected: str) -> dict[str, Any]:
    """Pause, then leave the pause by one of stop, abort or halt.

    `halt` is the one with no documented exit_status, and the docs say it
    skips cleanup entirely, so it may not produce a stop document at all.
    Everything here tolerates that rather than assuming a stop exists.
    """
    run_engine, recorder = engine()
    _run_to_pause(run_engine, _pausing_plan())
    leave = getattr(run_engine, method)
    error: str | None = None
    try:
        leave()
    except Exception as raised:  # noqa: BLE001 - a spike records, it does not judge
        error = f"{type(raised).__name__}: {raised}"
    return {
        "expected_aroc_status": expected,
        "left_pause_with": f"RE.{method}()",
        "raised_on_leaving": error,
        "state_after": run_engine.state,
        **recorder.as_json(),
    }


def scenario_stop_from_pause() -> dict[str, Any]:
    return _scenario_ending_from_pause("stop", "Completed")


def scenario_abort_from_pause() -> dict[str, Any]:
    return _scenario_ending_from_pause("abort", "Aborted")


def scenario_halt_from_pause() -> dict[str, Any]:
    return _scenario_ending_from_pause("halt", "unknown")


def scenario_plan_raises() -> dict[str, Any]:
    run_engine, recorder = engine()
    error: str | None = None
    try:
        run_engine(_failing_plan())
    except Exception as raised:  # noqa: BLE001 - the break is the scenario
        error = f"{type(raised).__name__}: {raised}"
    return {
        "expected_aroc_status": "Failed",
        "raised_out_of_the_engine": error,
        **recorder.as_json(),
    }


def scenario_real_plan() -> dict[str, Any]:
    """A stock plan with a simulated detector, for the sake of plan_args.

    The five scenarios above build their plans by hand, which keeps them
    free of `ophyd` but also leaves `plan_args` empty, and `plan_args` is
    the whole of question five. Only a plan from `bluesky.plans` fills it
    in, and those take devices.

    Skipped rather than fatal when `ophyd` is absent, so the rest of the
    spike still runs on the lighter dependency set.
    """
    try:
        from bluesky.plans import count
        from ophyd.sim import det
    except ImportError as missing:
        return {
            "expected_aroc_status": "Completed",
            "skipped": f"needs ophyd: {missing}",
            "documents": [],
            "transitions": [],
        }

    run_engine, recorder = engine()
    run_engine(count([det], num=2))
    return {"expected_aroc_status": "Completed", **recorder.as_json()}


SCENARIOS = {
    "completes": scenario_completes,
    "pause_resume_complete": scenario_pause_resume_complete,
    "stop_from_pause": scenario_stop_from_pause,
    "abort_from_pause": scenario_abort_from_pause,
    "halt_from_pause": scenario_halt_from_pause,
    "plan_raises": scenario_plan_raises,
    "real_plan": scenario_real_plan,
}


INTERRUPTION_DATA_KEY = "interruption"
"""The data key an interruption event carries.

Singular, and the Bluesky docs say `interruptions`. That plural is the
stream name, which is also what the descriptor is called, so reading the
docs and not the wire gets you an extractor that finds nothing and a
conclusion that the channel is dead. It is not dead. It works.
"""


def _interruption_values(captured: dict[str, Any]) -> list[str]:
    """Whatever the experimental interruptions stream put on the wire.

    Read out of event documents rather than assumed, because whether this
    channel reports anything at all is one of the questions.
    """
    found: list[str] = []
    for entry in captured["documents"]:
        if entry["name"] != "event":
            continue
        value = entry["doc"].get("data", {}).get(INTERRUPTION_DATA_KEY)
        if value is not None:
            found.append(str(value))
    return found


def _stop_field(captured: dict[str, Any], field: str) -> Any:
    for entry in captured["documents"]:
        if entry["name"] == "stop":
            return entry["doc"].get(field)
    return None



STAMP = REPORTER / "tests" / "collected.json"
"""Where the capture's provenance goes, beside the captures themselves.

Not inside the capture. `nodes.json` could hold it and `documents.json`
could not: its top level IS the scenario list, and `from_capture` in the
shipped reporter iterates it. Teaching shipped code to skip a metadata key
so a fixture can carry one is the wrong way round, so both collectors
write here instead and the two captures stay the shape their readers
expect.

Read by a person, when a refreshed capture turns an assertion red and the
question is which release moved.
"""


def stamp(capture: str, *packages: str) -> None:
    """Record what wrote a capture, and when, without disturbing the other.

    Read-modify-write, so running one collector leaves the other's entry
    alone. Duplicated in the sibling collector rather than shared: the two
    run in separate ephemeral environments with no project between them,
    which is the same reason the bound is copied in this file.
    """
    entries: dict[str, Any] = {}
    if STAMP.exists():
        entries = json.loads(STAMP.read_text(encoding="utf-8"))
    entries[capture] = {
        "collected": datetime.now(tz=UTC).date().isoformat(),
        "python": platform.python_version(),
        **{name: metadata.version(name) for name in packages},
    }
    STAMP.write_text(json.dumps(dict(sorted(entries.items())), indent=2) + "\n", encoding="utf-8")
    print(f"stamped {capture}: {entries[capture]}")


def main() -> None:
    results: dict[str, Any] = {}
    for name, scenario in SCENARIOS.items():
        results[name] = scenario()

    OUT.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    stamp(OUT.name, "bluesky", "ophyd")

    print(f"wrote {OUT.relative_to(REPORTER)}\n")
    header = f"{'scenario':<24} {'exit_status':<14} {'documents':<34} interruptions"
    print(header)
    print("-" * len(header))
    for name, captured in results.items():
        names = ",".join(entry["name"] for entry in captured["documents"]) or "(none)"
        status = _stop_field(captured, "exit_status")
        print(
            f"{name:<24} {str(status):<14} {names[:33]:<34} "
            f"{','.join(_interruption_values(captured)) or '(none)'}"
        )

    print("\nstate transitions, per scenario:")
    for name, captured in results.items():
        if not captured["transitions"]:
            print(f"  {name:<24} (none: {captured.get('skipped', 'no transitions')})")
            continue
        path = " -> ".join(
            [captured["transitions"][0]["from"]] + [t["to"] for t in captured["transitions"]]
        )
        print(f"  {name:<24} {path}")

    print("\nstop document fields, where a stop was emitted:")
    for name, captured in results.items():
        reason = _stop_field(captured, "reason")
        num_events = _stop_field(captured, "num_events")
        if _stop_field(captured, "uid") is None:
            print(f"  {name:<24} NO STOP DOCUMENT")
            continue
        print(f"  {name:<24} reason={reason!r} num_events={num_events}")

    for label in ("completes", "real_plan"):
        starts = [e["doc"] for e in results[label]["documents"] if e["name"] == "start"]
        if not starts:
            print(f"\nstart document for {label}: none ({results[label].get('skipped')})")
            continue
        start = starts[0]
        print(f"\nstart document for {label}:")
        print("  keys:      ", sorted(start))
        print("  plan_name: ", start.get("plan_name"))
        print("  detectors: ", json.dumps(start.get("detectors"), default=str))
        print("  plan_args: ", json.dumps(start.get("plan_args"), default=str))


if __name__ == "__main__":
    main()
