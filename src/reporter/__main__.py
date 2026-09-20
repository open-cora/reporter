"""Run the reporter against a file of captured documents.

    python -m reporter --config reporter.toml --replay documents.json

One command, and it is a replay rather than a daemon, because nothing
subscribes to a live engine yet. What it proves is the whole path with
only the engine simulated: configuration loads, every configured plan is
checked against AROC before anything is sent, documents go through the
translator and the relay, and the run appears in AROC with the engine's
own id on it.

That is what `spikes/bluesky_adapter/replay.py` does by printing a report.
The difference is that this is the shipped code doing it, against a real
AROC over a real socket, rather than a script imitating it in-process.

## The startup check earns its place here

Every plan in the map is looked up before the first document moves. A
typo in a plan id otherwise fails on the first run of that plan, at
whatever hour that is, with a 404 that reads like an AROC problem rather
than a configuration one.

## Durability, stated rather than discovered

Documents live in the relay's queue and nowhere else. Kill this process
and whatever was queued is gone, with nothing to replay it from. That is
at-most-once for anything in flight, and closing it needs a durable
transport between the engine and this process rather than anything here.
"""

import argparse
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

import httpx

from reporter.client import ArocClient
from reporter.config import ConfigError, ReporterConfig, load
from reporter.outcomes import Held, Outcome
from reporter.relay import Relay
from reporter.session import Session
from reporter.sources import from_capture

REQUEST_TIMEOUT_SECONDS = 10.0
"""How long one call to AROC may take before it counts as not arriving.

Bounded because the relay retries, and an unbounded request cannot be
retried: it occupies the worker until the socket gives up, which is the
queue backing up behind a single document.
"""


def main(argv: Sequence[str] | None = None) -> int:
    """Load, check, replay, and report. Returns a shell exit status."""
    arguments = _parse(argv)
    try:
        config = load(arguments.config)
    except ConfigError as problem:
        print(f"configuration: {problem}", file=sys.stderr)
        return 2

    documents = from_capture(arguments.replay)
    seen: list[Outcome] = []

    with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as http:
        client = ArocClient(http, config)
        missing = plans_aroc_does_not_hold(client, config)
        if missing:
            print(f"configuration: AROC holds no plan for {', '.join(missing)}", file=sys.stderr)
            return 2

        relay = Relay(Session(client, config), seen.append)
        relay.start()
        try:
            for name, document in documents:
                relay.submit(name, document)
        finally:
            relay.stop(timeout=60)

    return summarise(seen)


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="reporter",
        description="Replay captured engine documents into AROC.",
    )
    parser.add_argument("--config", type=Path, required=True, help="path to reporter.toml")
    parser.add_argument(
        "--replay",
        type=Path,
        required=True,
        help="path to captured documents, in the shape collect.py writes",
    )
    return parser.parse_args(argv)


def plans_aroc_does_not_hold(client: ArocClient, config: ReporterConfig) -> list[str]:
    return sorted(
        name for name, plan_id in config.plan_ids.items() if not client.plan_exists(plan_id)
    )


def summarise(seen: Sequence[Outcome]) -> int:
    """Print what happened, and fail the run if anything was held.

    Held is the only outcome worth a non-zero status: the other four are
    the reporter working, including `Unchanged`, which is what a replay of
    documents AROC has already seen looks like.
    """
    counts = Counter(type(outcome).__name__ for outcome in seen)
    for name in sorted(counts):
        print(f"  {name:<12} {counts[name]}")

    held = [outcome for outcome in seen if isinstance(outcome, Held)]
    for outcome in held:
        print(f"  held ({outcome.document_name}): {outcome.reason}", file=sys.stderr)
    return 1 if held else 0


if __name__ == "__main__":
    raise SystemExit(main())
