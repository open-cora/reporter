"""Reporting, Filing and Cataloguing, over the keeper's own HTTP API.

Three classes for three capabilities, against one service. They could
have been one object with three methods, and they are not, because they
are switched on separately: a deployment with nowhere to keep data has
a `Reporting` and neither of the others, and one object would have to
be passed as all three and then told to refuse most of itself.

    POST /executions/{id}/steps/{step}/run   an engine did something
    POST /datasets                           and it produced data
    POST /datasets/{id}/manifests            and this is what is in it

Two calls where there were five. The three that are gone all served one
job, bringing a run into existence here and finding it again afterwards.
The keeper composes and dispatches the work, so there is nothing to
create, nothing to resolve, and no configured routine to check at
startup.

`POST /operations` was already deliberately absent and stays absent for a
stronger reason than before. Whatever opens a run describes one
invocation and carries nothing a correct parameter schema could be
derived from, so an adapter that authored an operation would invent a
constraint. Now it would also be authoring the definition of work the
keeper itself had already composed.

## Where the status codes stop

Everything above takes `UnavailableError`, `RefusedError` or `DisagreedError` and knows
no numbers. `_refusal` below is the whole of the translation, and it is
the only place in this project that reads an HTTP status for meaning.

    403  not granted that command. configuration, and it will stay no.
    404  the execution or the step is not there, so the reference in the
         engine's metadata and the keeper disagree about what exists.
    409  the report does not follow the engine state the keeper holds.
    422  a key reused with a different body.
    429  and 5xx, which are the two that are worth asking again.

A request that never arrived is `UnavailableError` too, and that is a change
rather than a move. It used to travel as whatever the HTTP library
raised, and the worker retried `OSError` only, so a client whose
failures are not `OSError` had them escape into a thread with no handler
for them. Wrapping here means the worker catches one class and the
question of which library is in use stops being one it can get wrong.

## Redelivery, and why only one call carries a key

`Filing` sends an `Idempotency-Key` derived from the step and the
store's address together. The keeper keys its cache on
`(principal_id, key, surface_id)`, so a restarted reporter recomputes
the same key having persisted nothing, and the second registration of
one run's output returns the first one's dataset id rather than
recording a second dataset.

Both halves, for opposite reasons. Without the address, a run that
wrote two datasets would record one. Without the step, two runs that
wrote one address would record one, and the second would read forever
as a run whose data nobody filed. See `dataset_key_for`.

Naming the step in the key is not the same as deriving a dataset's
identity from it. The keeper deliberately did not do the second, so
that one-per-step would not be frozen into the schema, and it is not
frozen here: the address is in the key beside the step, so a run that
writes several still records several.

`Reporting` carries no key, deliberately. A repeated report is already
refused by the aggregate with a 409 naming the engine state it holds,
which is a better answer than a cached success: it distinguishes a
redelivery from a reporter that has lost track of a run.

## What it is given rather than what it builds

An HTTP client is passed in. That keeps the connection pool, timeouts,
retries and TLS where a deployment can set them, and it is what lets the
tests drive every path below through a transport that asserts on the
request instead of sending it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final, Protocol
from uuid import UUID

from reporter.seams import DisagreedError, RefusedError, UnavailableError

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from reporter.intents import RegisterDataset, ReportStepRun
    from reporter.seams import Entry, Manifest

_NO_CONTENT: Final = 204
_CREATED: Final = 201
_CONFLICT: Final = 409
_TOO_MANY: Final = 429
_SERVER_ERROR: Final = 500


def dataset_key_for(step_id: UUID, external_ref_value: str) -> str:
    """The key that makes a redelivered registration harmless.

    Derived rather than remembered, which is the whole point. The keeper
    keys on `(principal_id, key, surface_id)`, so a reporter running as
    one actor recomputes this after any restart having persisted nothing.

    Both halves, and each is load-bearing in a different direction.

    The address, because one run may write more than one dataset. A key
    naming only the step would give both registrations one note, so the
    second would come back holding the first's id and would never be
    recorded at all.

    The step, because more than one run may write one address. It is
    the same failure read the other way and it is the quieter of the
    two: the registration returns a success and an id, appends no
    event, and leaves that run recorded as having produced data nobody
    filed. The keeper does not treat an external reference as unique
    and says so, and a key that did was quietly making it so.

    Prefixed because a bare path in that table says nothing about what
    it was for, and somebody will eventually read the table.
    """
    return f"register-dataset:{step_id}:{external_ref_value}"


class Response(Protocol):
    """The part of an HTTP response this module reads.

    Narrower than any real client's response so the tests can supply one,
    and narrow enough that swapping the HTTP library is a change to
    whatever constructs the client rather than to this file.
    """

    @property
    def status_code(self) -> int: ...

    @property
    def text(self) -> str: ...

    def json(self) -> Any: ...


class HttpClient(Protocol):
    """The one verb this reporter sends the keeper, shaped as clients shape it."""

    def post(
        self,
        url: str,
        *,
        json: Mapping[str, Any] | None = ...,
        headers: Mapping[str, str] | None = ...,
    ) -> Response: ...


class HttpReporting:
    """Tells the keeper what an engine did to one step's run."""

    def __init__(self, http: HttpClient, base_url: str, token: str) -> None:
        self._http = http
        self._base_url = base_url
        self._token = token

    def record(self, intent: ReportStepRun) -> None:
        """Relay what the engine did to one step's run.

        No ids are passed in beside the intent. It already names the
        execution and the step, because whatever dispatched the work put
        them where the engine would hand them back.

        `engine_reference` travels on every report. The keeper records it
        on a start and ignores it on the others, which is stated on that
        route as the one place it is laxer than its sibling: a reporter
        draining an engine's stream repeats the same reference on every
        delivery, and refusing that would make the common case an error.
        """
        path = f"/executions/{intent.execution_id}/steps/{intent.step_id}/run"
        body: dict[str, Any] = {
            "reported": intent.reported,
            "engine_reference": intent.engine_reference,
            "occurred_at": _instant(intent.occurred_at),
        }
        response = _posted(self._http, f"{self._base_url}{path}", body, self._headers({}), path)
        if response.status_code != _NO_CONTENT:
            raise _refusal(response.status_code, response.text, method="POST", path=path)

    def _headers(self, extra: Mapping[str, str]) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}", **extra}


class HttpFiling:
    """Tells the keeper where the data a run produced is being kept.

    `scheme` is held here rather than asked for per call. It names the
    vocabulary a store's addresses belong to, so it describes the store
    this deployment keeps its data in, and a deployment that changes
    where its data lives changes both together. A caller holding an
    address should not also have to carry the fact of what kind of
    address it is.
    """

    def __init__(self, http: HttpClient, base_url: str, token: str, scheme: str) -> None:
        self._http = http
        self._base_url = base_url
        self._token = token
        self._scheme = scheme

    def record(self, intent: RegisterDataset) -> UUID:
        """Record where a run's output ended up, and return the keeper's id.

        `occurred_at` is the store's copy of the engine's own ending. It
        travels as `None` when the store holds no ending yet, and the
        keeper then stamps the moment it was told, which is honest and
        less precise.
        """
        path = "/datasets"
        body: dict[str, Any] = {
            "execution_id": str(intent.execution_id),
            "step_id": str(intent.step_id),
            "external_ref": {"scheme": self._scheme, "value": intent.external_ref_value},
            "occurred_at": _instant(intent.occurred_at),
        }
        headers = self._headers(
            {"Idempotency-Key": dataset_key_for(intent.step_id, intent.external_ref_value)}
        )
        response = _posted(self._http, f"{self._base_url}{path}", body, headers, path)
        if response.status_code != _CREATED:
            raise _refusal(response.status_code, response.text, method="POST", path=path)
        return UUID(str(response.json()["dataset_id"]))

    def _headers(self, extra: Mapping[str, str]) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}", **extra}


class HttpCataloguing:
    """Tells the keeper what is inside the data a run produced.

    Holds `scheme` for the same reason filing does, and holds the same
    one: this names the copy that was opened, and the copy that was
    opened is the copy that was filed.
    """

    def __init__(self, http: HttpClient, base_url: str, token: str, scheme: str) -> None:
        self._http = http
        self._base_url = base_url
        self._token = token
        self._scheme = scheme

    def record(self, dataset_id: UUID, address: str, manifest: Manifest) -> None:
        """Record what was found inside one copy of a run's output.

        No `occurred_at`. The other two calls carry one because they
        relay a moment that happened elsewhere, at a beamline this
        process was not watching. A description was taken here, a
        moment ago, so the keeper stamping its arrival is not an
        approximation of anything and sending a clock reading of our
        own would only be a second opinion about now.

        No idempotency key either. The far side refuses a description
        that repeats what it already holds, which is what a redelivery
        sends, and admits one that differs, which is what a second look
        sends. A key would have to be derived from the contents to tell
        those apart, which is the distinction the far side is already
        making from the contents themselves.
        """
        path = f"/datasets/{dataset_id}/manifests"
        body: dict[str, Any] = {
            "external_ref": {"scheme": self._scheme, "value": address},
            "convention": manifest.convention,
            "entries": [_entry(entry) for entry in manifest.entries],
        }
        response = _posted(self._http, f"{self._base_url}{path}", body, self._headers({}), path)
        if response.status_code != _NO_CONTENT:
            raise _refusal(response.status_code, response.text, method="POST", path=path)

    def _headers(self, extra: Mapping[str, str]) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}", **extra}


def _entry(entry: Entry) -> dict[str, Any]:
    """One entry as the keeper takes it.

    An absent extent travels as null rather than as an object of
    nulls, because the far side reads the absence as nobody having
    measured and an object of nulls as somebody having measured
    nothing.
    """
    extent = entry.extent
    return {
        "path": entry.path,
        "role": entry.role,
        "extent": None
        if extent is None
        else {
            "shape": list(extent.shape),
            "capacity": None if extent.capacity is None else list(extent.capacity),
            "dtype": extent.dtype,
        },
    }


def _posted(
    http: HttpClient,
    url: str,
    body: Mapping[str, Any],
    headers: Mapping[str, str],
    path: str,
) -> Response:
    """One request, with any failure to get an answer named as one kind.

    The catch is wide and its scope is one call. Whatever the client
    raises when it cannot reach the keeper is a request that did not
    arrive, and the alternative to naming every library's spelling of
    that is to let the ones nobody listed escape into the worker.
    """
    try:
        return http.post(url, json=body, headers=headers)
    except Exception as failure:
        raise UnavailableError(f"POST {path} did not arrive: {failure}") from failure


def _refusal(status: int, detail: str, *, method: str, path: str) -> Exception:
    """One HTTP status, as the one kind of failure it means.

    The whole of this project's knowledge that statuses are numbers.
    """
    if status == _CONFLICT:
        return DisagreedError(detail)
    said = f"{method} {path}: {status} {detail}"
    if status == _TOO_MANY or status >= _SERVER_ERROR:
        return UnavailableError(said)
    return RefusedError(said)


def _instant(moment: datetime | None) -> str | None:
    """A timestamp as the keeper takes it, or nothing.

    `None` travels rather than being dropped, because the field is
    optional on both commands and sending it explicitly says the delivery
    carried no time. The keeper then stamps the moment it was told.
    """
    return None if moment is None else moment.isoformat()


__all__ = [
    "HttpCataloguing",
    "HttpClient",
    "HttpFiling",
    "HttpReporting",
    "Response",
    "dataset_key_for",
]
