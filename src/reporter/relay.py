"""Take a document from the engine and let it go, immediately.

The one thing between this reporter and a stalled scan. A subscriber that
talks to AROC inside the engine's own thread makes every scan wait on a
network round trip, and at a facility where beamtime is the scarce thing
that is the property that gets a reporter removed.

So `submit` puts the document on a queue and returns in microseconds, and
a worker thread does the talking. The engine's thread never waits on AROC,
never waits on a retry, and never waits on a timeout.

What is on the other side of the queue is a function, not a `Session`.
The queue and the retries are the same whatever is behind them, and a
caller composes its own engine's translator with a session rather than
this module knowing about either.

## What this is not

It is not durable. Documents sit in memory, and a process that dies loses
whatever was queued, with no source to replay from: the engine does not
buffer, so a run that ended during a restart is simply never recorded.

That is a real gap and it is stated here rather than discovered. Closing
it takes a broker with a log between the engine and this process, at which
point the queue below becomes a consumer and `Relay` goes away. Until
then the reporter is at-most-once for anything in flight, and knowing that
is the difference between a limitation and a bug.

## Full is louder than slow

The queue is bounded. An unbounded one turns an AROC outage into memory
exhaustion, which takes the engine's host down with it, which is worse
than anything it was protecting against. When it is full `submit` refuses
rather than blocking, and the refusal is reported as `Held` like any other
document that could not be acted on.
"""

import queue
import threading
from collections.abc import Callable, Mapping, Sequence
from time import sleep
from typing import Any, Final

from reporter.client import RequestRefusedError
from reporter.outcomes import Held, Outcome
from reporter.stores import StoreRefusedError

DEFAULT_CAPACITY: Final = 1000
"""How many documents may wait before `submit` starts refusing.

Large enough to ride out a restart of the thing on the other end, small
enough that a long outage is noticed as dropped documents rather than as a
host running out of memory. It is a guess; the number worth having is
whatever a real stream's burst rate says.
"""

DEFAULT_RETRY_DELAYS: Final[tuple[float, ...]] = (0.5, 2.0, 5.0, 15.0)
"""How long to wait between attempts, and how many attempts there are.

Only failures worth retrying get here: a 429 or a 5xx from AROC or from a
store, or a request that never arrived. Everything else is already an
outcome by the time the worker sees it.

Bounded rather than forever, because a worker retrying one document
forever is a worker not draining the queue behind it, and an outage then
costs every later document as well as this one. Four attempts over about
twenty seconds rides out a restart; anything longer is what the durable
transport above is for.
"""

_STOP: Final = object()


Handle = Callable[[str, Mapping[str, Any]], Outcome]
"""What the worker calls, once per document.

An outcome means the document is finished with. Raising means the
opposite, and only a refusal from AROC, a refusal from a store, or a
request that did not arrive are retried, which is the contract
`Session.act` is written to.
"""


class Relay:
    """A queue and one worker, between an engine's thread and AROC."""

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

    def submit(self, name: str, document: Mapping[str, Any]) -> bool:
        """Hand over a document. Never blocks, never raises.

        Returns whether it was accepted. A caller running inside an engine
        has nothing useful to do with a `False` except carry on, which is
        why the drop is reported through `on_outcome` here rather than
        left for the caller to notice.
        """
        try:
            self._queue.put_nowait((name, dict(document)))
        except queue.Full:
            self._on_outcome(
                Held(
                    "the relay queue is full, so this document was dropped "
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
        self._worker = threading.Thread(target=self._drain, name="reporter-relay", daemon=True)
        self._worker.start()

    def stop(self, *, timeout: float | None = None) -> None:
        """Finish what is queued, then stop.

        Draining rather than dropping, because a clean shutdown is the one
        moment this reporter can avoid losing documents it already holds.
        A `timeout` bounds that: past it the worker is left to its daemon
        status and the process exits, which loses the remainder and is
        still better than refusing to shut down.
        """
        if self._worker is None:
            return
        self._queue.put(_STOP)
        self._worker.join(timeout)
        self._worker = None

    def _drain(self) -> None:
        while True:
            item = self._queue.get()
            if item is _STOP:
                return
            name, document = item
            self._on_outcome(self._attempt(name, document))

    def _attempt(self, name: str, document: Mapping[str, Any]) -> Outcome:
        """One document, retried while retrying could still help.

        Whatever is behind `handle` draws the line: it returns an outcome
        when the document is finished with, and raises when asking again
        might get a different answer. This loop is the only place that
        distinction is acted on.
        """
        last = ""
        for delay in (*self._retry_delays, None):
            try:
                return self._handle(name, document)
            except (RequestRefusedError, StoreRefusedError) as refusal:
                last = str(refusal)
            except OSError as failure:
                last = f"the request did not arrive: {failure}"
            if delay is None:
                break
            sleep(delay)

        return Held(
            f"gave up after {len(self._retry_delays) + 1} attempts: {last}",
            name,
        )


__all__ = ["DEFAULT_CAPACITY", "DEFAULT_RETRY_DELAYS", "Handle", "Relay"]
