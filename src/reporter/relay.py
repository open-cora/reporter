"""Take a delivery from the engine and let it go, immediately.

The one thing between this reporter and a stalled run. A subscriber that
talks to the keeper inside the engine's own thread makes every run wait
on a network round trip, and at a facility where beamtime is the scarce
thing that is the property that gets a reporter removed.

So `submit` puts the payload on a queue and returns in microseconds, and
a worker thread does the talking. The engine's thread never waits on the keeper,
never waits on a retry, and never waits on a timeout.

What is on the other side of the queue is a function, not a `Session`.
The queue and the retries are the same whatever is behind them, and a
caller composes its own engine's translator with a session rather than
this module knowing about either.

What arrives is a `name` and a payload this module never opens. A stream
of documents is one shape that fits and not the only one, so the word
here is `delivery`: the queue and the retries do not change when the
engine does, and neither should the vocabulary.

## What this is not

It is not durable. Deliveries sit in memory, and a process that dies loses
whatever was queued, with no source to replay from: the engine does not
buffer, so a run that ended during a restart is simply never recorded.

That is a real gap and it is stated here rather than discovered. Closing
it takes a broker with a log between the engine and this process, at which
point the queue below becomes a consumer and `Relay` goes away. Until
then the reporter is at-most-once for anything in flight, and knowing that
is the difference between a limitation and a bug.

## Full is louder than slow

The queue is bounded. An unbounded one turns a keeper outage into memory
exhaustion, which takes the engine's host down with it, which is worse
than anything it was protecting against. When it is full `submit` refuses
rather than blocking, and the refusal is reported as `Held` like any other
delivery that could not be acted on.
"""

import contextlib
import queue
import threading
from collections.abc import Callable, Mapping, Sequence
from time import sleep
from typing import Any, Final

from reporter.outcomes import Held, Outcome
from reporter.seams import UnavailableError

DEFAULT_CAPACITY: Final = 1000
"""How many deliveries may wait before `submit` starts refusing.

Large enough to ride out a restart of the thing on the other end, small
enough that a long outage is noticed as dropped deliveries rather than as a
host running out of memory. It is a guess; the number worth having is
whatever a real stream's burst rate says.
"""

DEFAULT_RETRY_DELAYS: Final[tuple[float, ...]] = (0.5, 2.0, 5.0, 15.0)
"""How long to wait between attempts, and how many attempts there are.

Only failures worth retrying get here, and they arrive as one class:
whatever is behind the handle raises `UnavailableError` when nothing answered
and asking again might get an answer. Everything else is already an
outcome by the time the worker sees it.

Bounded rather than forever, because a worker retrying one delivery
forever is a worker not draining the queue behind it, and an outage then
costs every later delivery as well as this one. One attempt and these
four delays, so five over about twenty seconds, which rides out a
restart; anything longer is what the durable transport above is for.
"""

_STOP: Final = object()


Handle = Callable[[str, Mapping[str, Any]], Outcome]
"""What the worker calls, once per delivery.

An outcome means the delivery is finished with, and `UnavailableError` means
the opposite. That is the whole contract, and it is the contract
`Session.act` is written to.

It used to be three classes, two of them named for a transport and one
of them `OSError`, and a seam whose library raised something else had
its failures escape into a thread with no handler for them. A worker
that dies looks exactly like a beamline that is not running, which is
the shape of failure worth designing out rather than catching wider.
"""


class Relay:
    """A queue and one worker, between an engine's thread and the keeper."""

    def __init__(
        self,
        handle: Handle,
        on_outcome: Callable[[Outcome], None],
        *,
        capacity: int = DEFAULT_CAPACITY,
        retry_delays: Sequence[float] = DEFAULT_RETRY_DELAYS,
    ) -> None:
        self._handle = handle
        self._on_outcome = on_outcome
        self._retry_delays = tuple(retry_delays)
        self._queue: queue.Queue[Any] = queue.Queue(maxsize=capacity)
        self._worker: threading.Thread | None = None
        self._stopping = threading.Event()

    def submit(self, name: str, payload: Mapping[str, Any]) -> bool:
        """Hand over one delivery. Never blocks, never raises.

        Returns whether it was accepted. A caller running inside an engine
        has nothing useful to do with a `False` except carry on, which is
        why both ways of refusing one are reported through `on_outcome`
        here rather than left for the caller to notice.

        A stopped relay refuses rather than accepts. Nothing drains the
        queue once the worker is gone, so an accepted delivery would sit
        in it unreported while the caller was told it had been taken. An
        engine outlives this object whenever a process stops the relay
        without unsubscribing, and the recipe for running one inside an
        engine does not unsubscribe.
        """
        if self._stopping.is_set():
            self._report(
                Held(
                    "this relay has stopped, so the delivery was refused "
                    "and whatever it said about a run is lost",
                    name,
                )
            )
            return False
        try:
            self._queue.put_nowait((name, dict(payload)))
        except queue.Full:
            self._report(
                Held(
                    "the relay queue is full, so this delivery was dropped "
                    "and whatever it said about a run is lost",
                    name,
                )
            )
            return False
        return True

    def start(self) -> None:
        """Begin draining, on a thread of this relay's own."""
        if self._worker is not None:
            raise RuntimeError("This relay is already running.")
        self._stopping.clear()
        self._worker = threading.Thread(target=self._drain, name="reporter-relay", daemon=True)
        self._worker.start()

    def stop(self, *, timeout: float | None = None) -> None:
        """Finish what is queued, then stop.

        Draining rather than dropping, because a clean shutdown is the one
        moment this reporter can avoid losing deliveries it already holds.
        A `timeout` bounds that: past it the worker is left to its daemon
        status and the process exits, which loses the remainder and is
        still better than refusing to shut down.

        The flag is what makes that last part true, and the sentinel
        alone did not. Putting one on a bounded queue blocks while the
        queue is full, and a full queue is precisely what a long outage
        leaves behind, so a stop arriving at the worst moment waited on
        the worker it was trying to end and never reached its own
        timeout. The worker reads the flag too, and stops once it has
        nothing left rather than only once it reaches a sentinel that may
        not have fitted.
        """
        if self._worker is None:
            return
        self._stopping.set()
        with contextlib.suppress(queue.Full):
            self._queue.put_nowait(_STOP)
        self._worker.join(timeout)
        self._worker = None

    def _drain(self) -> None:
        while True:
            item = self._queue.get()
            if item is _STOP:
                return
            name, payload = item
            self._report(self._attempt(name, payload))
            if self._stopping.is_set() and self._queue.empty():
                return

    def _report(self, outcome: Outcome) -> None:
        """Hand one outcome to the caller's sink, surviving a sink that raises.

        What `on_outcome` may do is nowhere specified, where `Handle` is
        specified closely, and it is called on both of the threads this
        module exists to keep alive. On the worker a raising sink kills
        the thread, and a reporter whose worker has died looks exactly
        like a beamline that is not running. On the engine's own thread
        it reaches whoever subscribed, which is the scan.

        Suppressed rather than reported onward, because a sink that just
        failed is not a sink a failure can be reported through. The one
        this ships with prints, and printing fails when the stream a
        service manager handed the process goes away.
        """
        with contextlib.suppress(Exception):
            self._on_outcome(outcome)

    def _attempt(self, name: str, payload: Mapping[str, Any]) -> Outcome:
        """One delivery, retried while retrying could still help.

        Whatever is behind `handle` draws the line: it returns an outcome
        when the delivery is finished with, and raises when asking again
        might get a different answer. This loop is the only place that
        distinction is acted on.
        """
        last = ""
        for delay in (*self._retry_delays, None):
            try:
                return self._handle(name, payload)
            except UnavailableError as unavailable:
                last = str(unavailable)
            if delay is None:
                break
            sleep(delay)

        return Held(
            f"gave up after {len(self._retry_delays) + 1} attempts: {last}",
            name,
        )


__all__ = ["DEFAULT_CAPACITY", "DEFAULT_RETRY_DELAYS", "Handle", "Relay"]
