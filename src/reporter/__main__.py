"""Run the reporter, against a live engine or against a capture.

    python -m reporter --config reporter.toml --subscribe tcp://127.0.0.1:5568
    python -m reporter --config reporter.toml --replay documents.json

One command and two sources, because the second one is how the first is
tested. A replay proves the whole path with only the engine simulated, and
it keeps doing that after a live subscription exists: it needs no beamline
and it is the same shipped code either way.

The difference between them is only that a subscription does not end.
Both load configuration, check a configured store answers, and put each
document through the translator and the relay.

## A third way to run this, which is not a command

Inside the engine's own process, `Relay.submit` is the subscription
callback and nothing here is involved. The README has the recipe.

## The startup check earns its place here

A configured store is reached for once before the first document moves.
All it asks is whether something answers where the writer is supposed to
be pointed; whether runs actually land there is not knowable before one
does. A store that cannot be reached at all is worth refusing to start
over, because the alternative is a reporter that relays every report and
quietly files no data.

There used to be a second check, looking up every configured plan id.
It went with the plan map: this reporter resolves nothing now, so there
is no configured reference left that the keeper could fail to recognise. What
replaces it is not a startup check at all, because the reference arrives
per document: an execution or step the keeper does not hold comes back as a
404 on the report, and is `Held`.

## Durability, stated rather than discovered

Documents live in the relay's queue and nowhere else, and a 0MQ
subscription has nothing behind it to ask again. Kill this process and
whatever was queued is gone, along with whatever was published while it
was down. That is at-most-once, and closing it needs a transport that
keeps a log rather than anything here.

Restarting costs more than it used to, and the extra cost is in the
translator: the keeper reference for a run in flight lives there and
cannot be recovered, so a scan that was running through a restart is
reported on no further.
"""

import argparse
import signal
import sys
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from types import FrameType
from typing import Protocol

import httpx

from reporter.adapters.bluesky_documents import documents_into
from reporter.adapters.capture_replay import from_capture
from reporter.adapters.keeper_http import (
    HttpCataloguing,
    HttpClient,
    HttpFiling,
    HttpReporting,
)
from reporter.adapters.store_http import HttpLocating, StoreHttpClient
from reporter.adapters.tomoscan_records import from_tomoscan, records_into
from reporter.adapters.zmq_subscription import DecodeError, from_subscription
from reporter.config import ConfigError, ReporterConfig, load
from reporter.outcomes import Held, Kept, Outcome
from reporter.relay import Handle, Relay
from reporter.seams import (
    Cataloguing,
    Delivery,
    Describing,
    Filing,
    Locating,
    RefusedError,
    UnavailableError,
)
from reporter.session import Session

REQUEST_TIMEOUT_SECONDS = 10.0
"""How long one call to the keeper may take before it counts as not arriving.

Bounded because the relay retries, and an unbounded request cannot be
retried: it occupies the worker until the socket gives up, which is the
queue backing up behind a single document.
"""

DRAIN_TIMEOUT_SECONDS = 60.0
"""How long shutdown waits for the relay to finish what it is holding."""


class Tally:
    """What a run came to, without keeping every outcome to say so.

    Counts rather than a list, because a subscription runs for as long as
    the engine does and a list of every document it ever saw is a leak
    with a summary attached.

    `Held` is printed when it happens rather than at the end, because a
    process that reports it on shutdown reports it to nobody.

    A `Kept` that could not say what is inside the data is printed too,
    and it is deliberately not a `Held`. The run is recorded and so is
    where its output went, so nothing is lost that cannot be asked for
    again; what would be lost is anybody knowing to ask. A tally that
    counted it and said nothing would leave a reporter describing
    nothing for a month while every number looked right.

    Written from the relay's single worker thread and read after that
    thread has been joined, which is what makes a plain `Counter` enough.
    """

    def __init__(self) -> None:
        self._counts: Counter[str] = Counter()

    def record(self, outcome: Outcome) -> None:
        self._counts[type(outcome).__name__] += 1
        if isinstance(outcome, Held):
            print(f"  held ({outcome.origin}): {outcome.reason}", file=sys.stderr)
        if isinstance(outcome, Kept) and outcome.undescribed is not None:
            print(f"  kept, undescribed: {outcome.undescribed}", file=sys.stderr)

    def report(self) -> int:
        """Print what happened, and fail the run if anything was held."""
        for name in sorted(self._counts):
            print(f"  {name:<12} {self._counts[name]}")
        return 1 if self._counts[Held.__name__] else 0


def main(argv: Sequence[str] | None = None) -> int:
    """Load, check, run, and report. Returns a shell exit status."""
    arguments = _parse(argv)
    try:
        config = load(arguments.config)
    except ConfigError as problem:
        print(f"configuration: {problem}", file=sys.stderr)
        return 2

    tally = Tally()
    unreadable: str | None = None
    with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as http:
        reporting = HttpReporting(http, config.base_url, config.token)
        filing, locating = dataset_leg(http, config)
        unreachable = store_that_does_not_answer(locating, config)
        if unreachable is not None:
            print(f"configuration: {unreachable}", file=sys.stderr)
            return 2
        try:
            describing, cataloguing = contents_leg(http, config)
        except ConfigError as problem:
            print(f"configuration: {problem}", file=sys.stderr)
            return 2

        session = Session(reporting, filing, locating, describing, cataloguing)
        relay = Relay(handle_for(arguments, session), tally.record)
        relay.start()
        try:
            unreadable = drive(deliveries(arguments), relay)
        finally:
            relay.stop(timeout=DRAIN_TIMEOUT_SECONDS)

    status = tally.report()
    if unreadable is not None:
        print(f"subscription: {unreadable}", file=sys.stderr)
        return 2
    return status


def handle_for(arguments: argparse.Namespace, session: Session) -> Handle:
    """The translator that matches the source the arguments asked for.

    Separate from `main` because getting it wrong is silent. A record
    stream read through the document grammar matches no document name,
    so every scan becomes `Unmappable`, nothing is ever reported, and
    the run ends with a tidy tally and a zero exit status. A reporter
    that does nothing and says it went fine is worse than one that
    crashes, so this pairing is somewhere a test can reach.
    """
    if arguments.records is not None:
        return records_into(session)
    return documents_into(session)


def deliveries(arguments: argparse.Namespace) -> Iterator[Delivery]:
    """The source the arguments asked for.

    Named for what all three produce rather than for what the first one
    produced. A TomoScan server publishes no documents, and calling the
    thing that reads it a document source is how the engine's vocabulary
    crosses back over a boundary drawn to keep it out.
    """
    if arguments.replay is not None:
        return from_capture(arguments.replay)
    if arguments.records is not None:
        return from_tomoscan(arguments.records)
    return from_subscription(arguments.subscribe, prefix=arguments.prefix.encode())


def drive(documents: Iterator[Delivery], relay: Relay) -> str | None:
    """Hand every document over, until they run out or somebody stops it.

    Returns what made the stream unreadable, or `None` for either of the
    two ordinary endings: a capture that ran out, or a subscription that
    was stopped. Being stopped is ordinary because stopping is the only
    way a subscription ever ends, and the relay still drains what it holds
    on the way out.

    A frame that cannot be decoded ends the run rather than being skipped.
    Every frame on a stream is encoded the same way, so one unreadable
    frame means the publisher and this disagree about the encoding and all
    of them are unreadable. Carrying on would drop every run on that
    stream while looking like a reporter that was working.
    """
    try:
        for name, document in documents:
            relay.submit(name, document)
    except KeyboardInterrupt:
        print("\nstopping, and finishing what is already queued", file=sys.stderr)
    except DecodeError as unreadable:
        return str(unreadable)
    return None


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="reporter",
        description="Relay one engine's documents to the keeper as step-run reports.",
    )
    parser.add_argument("--config", type=Path, required=True, help="path to reporter.toml")

    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--subscribe",
        metavar="ADDRESS",
        help="0MQ endpoint an engine publishes to, such as tcp://127.0.0.1:5568",
    )
    source.add_argument(
        "--replay",
        type=Path,
        metavar="PATH",
        help="path to captured documents, in the shape collect.py writes",
    )
    source.add_argument(
        "--records",
        metavar="PREFIX",
        help="record prefix of a TomoScan server, such as 2bmb:TomoScan:",
    )

    parser.add_argument(
        "--prefix",
        default="",
        help="publisher prefix to select, when several publish to one proxy",
    )

    arguments = parser.parse_args(argv)
    if arguments.prefix and arguments.subscribe is None:
        parser.error("--prefix selects among publishers, so it needs --subscribe")
    return arguments


class Transport(HttpClient, StoreHttpClient, Protocol):
    """One client reaching both services, which is how they share a pool.

    The two adapters declare their own narrow shapes and neither knows
    the other exists. This names the intersection, because a single
    entrypoint hands one object to both and the timeouts, the retries and
    the TLS are a deployment's to set once.
    """


def dataset_leg(http: Transport, config: ReporterConfig) -> tuple[Filing | None, Locating | None]:
    """Each half of the dataset leg, switched on by its own table.

    Filing needs the vocabulary an address belongs to and locating needs
    a store to ask, and those are different facts. An engine answering
    with a path gives an address and nothing to resolve, so that
    deployment files and never locates; one answering with a name
    resolves first and then files, so it does both. Either may be absent,
    and absence is a configuration this reporter supports rather than a
    degraded one.

    The pairing a `Session` cannot finish, locating with nothing to file,
    is still unconstructable, but it is `load` that refuses it now rather
    than the shape of this function.

    One HTTP client serves both the keeper and the store, so timeouts and
    the connection pool are set in a single place.
    """
    filing = (
        None
        if config.external_ref_scheme is None
        else HttpFiling(http, config.base_url, config.token, config.external_ref_scheme)
    )
    locating = (
        None
        if config.store is None
        else HttpLocating(http, config.store.base_url, config.store.root)
    )
    return filing, locating


def contents_leg(
    http: Transport, config: ReporterConfig
) -> tuple[Describing | None, Cataloguing | None]:
    """Reading what is inside the data, and telling the keeper, or neither.

    Switched on by one key, because the two halves are useless apart. A
    reader with nowhere to send what it found records nothing, and a
    sender with nothing to send never sends.

    The describer is imported here rather than at the top of this
    module. Its library is an extra, this module is imported whatever a
    deployment is running, and a top-level import would make every
    reporter at every beamline need a format library to start. That is
    not a hypothetical: the subscription adapter was written that way
    and stopped the process booting on the extras the deploy script
    passes.

    Which leaves one failure this has to name rather than raise: a
    deployment that asks for a describer and did not install the extra
    it needs. Configuration cannot catch that, because the name is
    perfectly good and it is the virtualenv that is short. So it is
    refused here, at startup, with the extra to re-sync named, rather
    than on the first scan that ends.
    """
    if config.describer is None or config.external_ref_scheme is None:
        return None, None
    try:
        from reporter.adapters.dxchange_hdf5 import DxchangeHdf5Describing
    except ImportError as missing:
        raise ConfigError(
            f"dataset.describer is {config.describer!r} and this virtualenv cannot "
            f"build one. Re-sync with --extra describe-hdf5, or remove the key to "
            f"file addresses and say nothing about what is in the data. ({missing})"
        ) from missing

    built: dict[str, Callable[[], Describing]] = {"dxchange-hdf5": DxchangeHdf5Describing}
    return (
        built[config.describer](),
        HttpCataloguing(http, config.base_url, config.token, config.external_ref_scheme),
    )


def store_that_does_not_answer(store: Locating | None, config: ReporterConfig) -> str | None:
    """Whether a configured store answers, said the way a person would fix it.

    The probe asks for a run that cannot exist, so a reachable store says
    it holds nothing and an unreachable one raises. That keeps the check
    free of any assumption about what is in there already, which matters
    because a reporter is usually started before the first scan of the
    day.
    """
    if store is None or config.store is None:
        return None
    try:
        store.locate("a-run-that-cannot-exist")
    except RefusedError as refusal:
        return f"the store at {config.store.base_url} refused: {refusal}"
    except UnavailableError as unreachable:
        return f"the store at {config.store.base_url} did not answer: {unreachable}"
    return None


def stop_on_termination() -> None:
    """Make a service manager's stop signal behave like Ctrl-C.

    A reporter is a daemon, and a daemon is stopped by SIGTERM rather than
    by somebody pressing a key. Without this, the one moment this process
    can avoid losing documents is the moment it is killed during: the
    relay drains on the way out, and a default SIGTERM never reaches the
    way out.

    Ctrl-C already arrives as `KeyboardInterrupt`, so the cheapest way to
    give the two signals one shutdown is to make the second one arrive
    that way too.
    """

    def interrupt(number: int, frame: FrameType | None) -> None:
        _ = number, frame
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)


if __name__ == "__main__":
    stop_on_termination()
    raise SystemExit(main())
