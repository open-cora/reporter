"""Where a run's output ended up, asked of whatever is keeping it.

The second thing this reporter reads. An engine says a run happened and a
store says where its data landed, and joining those two is the whole of
what the dataset leg adds.

A `StoreLookup` answers one question: given the engine's own id for a run,
where is the data, and when did whatever wrote it finish. Everything
store-shaped stops here, the way everything engine-shaped stops in
`sources` and `translate`.

## The address is computed, not read

The store reports two spellings of one node's address depending on how the
handle was obtained, a leading empty segment present or absent. Two
spellings are two values, two values are two records of one body of data,
and nothing downstream can tell. So `node_path` is not tidying applied to
an address, it is part of the definition of the address, and it is written
once here rather than at every place that builds or checks one.

A spike is where that came from, and
`tests/nodes.json` is the capture it came out of.

## No client library, and the reason is measured rather than argued

The store's own Python client reads two fields off the `data` member of an
ordinary HTTP response, so an adapter reading that response directly gets
the same address, byte for byte. The spike checks both ways against each
other on four runs and they agree on all four.

That leaves one dependency where there would have been two, and it is the
one this reporter already has for the keeper. It is the same reasoning that
keeps the engine's library out of `sources`, arrived at from the other
direction: there the wire was simple enough, here the client turned out to
be thin enough.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Protocol

METADATA_ROUTE: Final = "/api/v1/metadata"
"""The route a node's record is served on.

Written out rather than discovered, because the alternative is asking the
store for its own links and then following one, which is a round trip to
learn a constant.
"""


def node_path(ancestors: Iterable[Any], key: Any) -> str:
    """One node's address, spelled the single way a record may carry it.

    Empty segments are dropped, which is the whole of the normalisation
    and the whole of why this is a function. A handle obtained by creating
    a node carries a leading empty ancestor and a handle obtained by
    looking one up does not, so the store will hand over either
    `raw/<uid>` or `/raw/<uid>` for the same node depending on nothing
    the record should care about.
    """
    return "/".join(str(segment) for segment in (*ancestors, key) if str(segment))


class StoreResponse(Protocol):
    """The part of an HTTP response the lookup below reads."""

    @property
    def status_code(self) -> int: ...

    def json(self) -> Any: ...

    @property
    def text(self) -> str: ...


class StoreHttpClient(Protocol):
    """The one verb a store is read with.

    Declared here rather than imported from `client`, which has a wider
    pair of the same shape. That module talks to the keeper and this one may not
    name it, which is the rule `tests/test_the_halves_stay_apart.py` keeps
    and the reason a different store is an adapter swap. The duplication
    is six lines and it buys a lookup that cannot reach the keeper by accident.
    """

    def get(self, url: str) -> StoreResponse: ...


@dataclass(frozen=True)
class Location:
    """Where one body of data is, and when whatever wrote it finished.

    `occurred_at` is `None` when the store holds no ending for the run,
    and that is worth reading as a signal rather than as a missing field.
    A store that has the node but not its ending is a store the reporter
    got to first, which in one process means it subscribed before the
    writer rather than after it. The keeper then stamps the moment it was told,
    so nothing is lost but the record is less true than it could be.
    """

    path: str
    occurred_at: datetime | None


class StoreLookup(Protocol):
    """Whatever can say where a run's data ended up.

    One method, because one question is all the dataset leg asks. A
    deployment with no store configured has no lookup at all rather than
    one that always answers `None`, so that "the leg is switched off" and
    "the store has nothing" stay different states.
    """

    def locate(self, run_uid: str) -> Location | None:
        """The data this run produced, or `None` if the store has none."""
        ...


class StoreRefusedError(Exception):
    """The store answered, and the answer was not a node.

    Carries the status for the same reason the keeper's refusal does: waiting
    helps for some of them and not for others, and only the caller can
    decide. A run the store does not hold is not this. That is a 404 and
    it comes back as `None`, because "no data for this run" is an answer
    rather than a failure.
    """

    def __init__(self, status: int, detail: str, *, url: str) -> None:
        super().__init__(f"GET {url}: {status} {detail}")
        self.status = status
        self.detail = detail
        self.url = url


class HttpStoreLookup:
    """Reads a store's metadata route, with no store library in the way.

    `root` is the container the writer points at, and it is configuration
    rather than something to discover: a search does not descend, so a
    reporter cannot find a run by uid without already knowing where to
    look. A misconfigured one finds nothing and says so, which is a better
    failure than finding the wrong thing.
    """

    def __init__(self, http: StoreHttpClient, base_url: str, root: str) -> None:
        self._http = http
        self._base_url = base_url.rstrip("/")
        self._root = root.strip("/")

    def locate(self, run_uid: str) -> Location | None:
        url = self._url(run_uid)
        response = self._http.get(url)
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise StoreRefusedError(response.status_code, response.text, url=url)
        return _as_location(response.json())

    def _url(self, run_uid: str) -> str:
        return f"{self._base_url}{METADATA_ROUTE}/{node_path([self._root], run_uid)}"


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
    digit, so this is the same conversion `engine_instant` makes and it is
    deliberately not shared with it. That one reads a document and this
    one reads a number somebody already dug out of a response, and folding
    them together would put a document-shaped signature on the store's
    side of the reporter.
    """
    if not isinstance(seconds, (int, float)) or isinstance(seconds, bool):
        return None
    return datetime.fromtimestamp(float(seconds), tz=UTC)


__all__ = [
    "METADATA_ROUTE",
    "HttpStoreLookup",
    "Location",
    "StoreHttpClient",
    "StoreLookup",
    "StoreRefusedError",
    "StoreResponse",
    "node_path",
    "store_instant",
]
