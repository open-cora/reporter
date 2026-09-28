"""Locating, over a store's own metadata route.

An engine says a run happened and a store says where its data landed.
Joining those two is the whole of what the dataset leg adds, and this is
the half that answers the second question.

## The address is computed, not read

The store reports two spellings of one node's address depending on how
the handle was obtained, a leading empty segment present or absent. Two
spellings are two values, two values are two records of one body of
data, and nothing downstream can tell. So `node_path` is not tidying
applied to an address, it is part of the definition of the address, and
it is written once here rather than at every place that builds or checks
one.

A spike is where that came from, and `tests/nodes.json` is the capture it
came out of.

## No client library, and the reason is measured rather than argued

The store's own Python client reads two fields off the `data` member of
an ordinary HTTP response, so an adapter reading that response directly
gets the same address, byte for byte. The spike checks both ways against
each other on four runs and they agree on all four.

That leaves one dependency where there would have been two, and it is
the one this reporter already has for the keeper. It is the same
reasoning that keeps the engine's library out of the subscription,
arrived at from the other direction: there the wire was simple enough,
here the client turned out to be thin enough.

## What a 404 is, and what it is not

A run the store does not hold comes back as `None` rather than as a
refusal, because "no data for this run" is an answer. Every other
non-success status is one of the three failures the seams declare, and
`_refusal` below is where a number becomes one of them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final, Protocol

from reporter.seams import Location, RefusedError, UnavailableError

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

METADATA_ROUTE: Final = "/api/v1/metadata"
"""The route a node's record is served on.

Written out rather than discovered, because the alternative is asking
the store for its own links and then following one, which is a round
trip to learn a constant.
"""

_OK: Final = 200
_NOT_FOUND: Final = 404
_TOO_MANY: Final = 429
_SERVER_ERROR: Final = 500


def node_path(ancestors: Iterable[Any], key: Any) -> str:
    """One node's address, spelled the single way a record may carry it.

    Empty segments are dropped, which is the whole of the normalisation
    and the whole of why this is a function. A handle obtained by
    creating a node carries a leading empty ancestor and a handle
    obtained by looking one up does not, so the store will hand over
    either `raw/<uid>` or `/raw/<uid>` for the same node depending on
    nothing the record should care about.
    """
    return "/".join(str(segment) for segment in (*ancestors, key) if str(segment))


class StoreResponse(Protocol):
    """The part of an HTTP response this module reads."""

    @property
    def status_code(self) -> int: ...

    def json(self) -> Any: ...

    @property
    def text(self) -> str: ...


class StoreHttpClient(Protocol):
    """The one verb a store is read with.

    Declared here rather than imported from the keeper's adapter, which
    has a client of the same shape pointed somewhere else. Two outside
    systems that shared a declaration would be joined through this
    package, and the duplication is six lines against a lookup that
    cannot reach the keeper by accident.
    """

    def get(self, url: str) -> StoreResponse: ...


class HttpLocating:
    """Reads a store's metadata route, with no store library in the way.

    `root` is the container the writer points at, and it is configuration
    rather than something to discover: a search does not descend, so a
    reporter cannot find a run by reference without already knowing where
    to look. A misconfigured one finds nothing and says so, which is a
    better failure than finding the wrong thing.
    """

    def __init__(self, http: StoreHttpClient, base_url: str, root: str) -> None:
        self._http = http
        self._base_url = base_url.rstrip("/")
        self._root = root.strip("/")

    def locate(self, run_reference: str) -> Location | None:
        url = self._url(run_reference)
        try:
            response = self._http.get(url)
        except Exception as failure:
            raise UnavailableError(f"GET {url} did not arrive: {failure}") from failure

        if response.status_code == _NOT_FOUND:
            return None
        if response.status_code != _OK:
            raise _refusal(response.status_code, response.text, url=url)
        return _as_location(response.json())

    def _url(self, run_reference: str) -> str:
        return f"{self._base_url}{METADATA_ROUTE}/{node_path([self._root], run_reference)}"


def _refusal(status: int, detail: str, *, url: str) -> Exception:
    """One HTTP status, as the one kind of failure it means.

    A store has no state this reporter can be out of step with, so
    nothing here produces `DisagreedError`. It asks a question and gets an
    answer or does not.
    """
    said = f"GET {url}: {status} {detail}"
    if status == _TOO_MANY or status >= _SERVER_ERROR:
        return UnavailableError(said)
    return RefusedError(said)


def _as_location(body: Mapping[str, Any]) -> Location:
    """One node's record, as the store's HTTP surface returns it.

    The envelope is `data.attributes`, and the two fields read out of it
    are the ones the store's own client reads. Everything else it carries
    is left alone: the structure, the size and the typed marker saying
    what kind of thing the node is are all facts the store owns, and a
    copy on a Custody record would go stale the first time they changed.
    """
    data: Mapping[str, Any] = body.get("data") or {}
    attributes: Mapping[str, Any] = data.get("attributes") or {}
    metadata: Mapping[str, Any] = attributes.get("metadata") or {}
    ending: Mapping[str, Any] = metadata.get("stop") or {}
    return Location(
        path=node_path(attributes.get("ancestors") or [], data.get("id") or ""),
        occurred_at=store_instant(ending.get("time")),
    )


def store_instant(seconds: Any) -> datetime | None:
    """A store's timestamp, as an instant the keeper will accept.

    The store keeps the engine's own `time` fields verbatim, to the last
    digit, so this is the same conversion `engine_instant` makes and it
    is deliberately not shared with it. That one reads a delivery and
    this one reads a number somebody already dug out of a response, and
    folding them together would put a delivery-shaped signature on the
    store's side of the reporter.
    """
    if not isinstance(seconds, (int, float)) or isinstance(seconds, bool):
        return None
    return datetime.fromtimestamp(float(seconds), tz=UTC)


__all__ = [
    "METADATA_ROUTE",
    "HttpLocating",
    "StoreHttpClient",
    "StoreResponse",
    "node_path",
    "store_instant",
]
