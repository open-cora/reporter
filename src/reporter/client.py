"""The two calls this reporter makes to AROC, and what it does with a no.

The imperative shell on the sending side. It turns an `Intent` into a
request and a response into either an id or a typed refusal, and it holds
no decisions: which deliveries matter comes from the translator, and
which records they belong to comes from the engine's own metadata.

## Two calls, where there were five

    POST /executions/{id}/steps/{step}/run   an engine did something
    POST /datasets                           and it produced data

The three that are gone all served one job: bringing a run into existence
here and finding it again afterwards. AROC composes and dispatches the
work now, so there is nothing to create, nothing to resolve, and no
configured plan to check at startup.

`POST /plans` was already deliberately absent and stays absent for a
stronger reason than before. Whatever opens a run describes one
invocation and carries nothing a correct parameter schema could be
derived from, so an adapter that authored a plan would invent a
constraint. Now it would also be authoring the definition of work AROC
itself had already composed.

## Redelivery, and why only one call carries a key

`register_dataset` sends an `Idempotency-Key` derived from the store's
address. AROC keys its cache on `(principal_id, key, surface_id)`, so a
restarted reporter recomputes the same key having persisted nothing, and
the second registration of one address returns the first one's dataset id
rather than recording a second dataset.

The address rather than the step, because one acquisition may write more
than one. A key naming the step would give both registrations one note,
so the second would come back holding the first dataset's id and would
never be recorded at all. AROC deliberately did not derive a dataset's
identity from the step that produced it, so that one-per-step would not
be frozen into the schema, and keying the retry note on the step would
put it back somewhere no migration announces.

`report_step_run` carries no key, deliberately. A repeated report is
already refused by the aggregate with a 409 naming the engine state it
holds, which is a better answer than a cached success: it distinguishes
a redelivery from a reporter that has lost track of a run.

## What it is given rather than what it builds

An HTTP client is passed in. That keeps the connection pool, timeouts,
retries and TLS where a deployment can set them, and it is what lets the
tests drive every path below through a transport that asserts on the
request instead of sending it.
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from reporter.config import ReporterConfig
from reporter.intents import RegisterDataset, ReportStepRun


def dataset_key_for(external_ref_value: str) -> str:
    """The key that makes a redelivered registration harmless.

    Derived rather than remembered, which is the whole point. AROC's store
    keys on `(principal_id, key, surface_id)`, so a reporter running as
    one actor recomputes this after any restart having persisted nothing.

    A dataset is identified by where the data is, so this names an
    address. Prefixed because a bare path in that table says nothing about
    what it was for, and somebody will eventually read the table.
    """
    return f"register-dataset:{external_ref_value}"


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
    """The two verbs this reporter uses, shaped the way every client shapes them."""

    def get(self, url: str, *, params: Mapping[str, str] | None = ...) -> Response: ...

    def post(
        self,
        url: str,
        *,
        json: Mapping[str, Any] | None = ...,
        headers: Mapping[str, str] | None = ...,
    ) -> Response: ...


class RequestRefusedError(Exception):
    """AROC answered, and the answer was no.

    Carries the status because the statuses mean different things to
    whatever is driving this, and only it can decide:

        403  this reporter is not granted that command. configuration.
        404  the execution or the step is not there, which means the
             reference in the engine's metadata and AROC disagree.
        409  the report does not follow the engine state AROC holds. a
             redelivery, usually harmless, and the one refusal a caller
             should expect.
        422  a key reused with a different body.

    A transport failure is not this. It comes out of the HTTP client
    unchanged, because a request that never arrived and a request that was
    turned down want opposite handling.
    """

    def __init__(self, status: int, detail: str, *, method: str, path: str) -> None:
        super().__init__(f"{method} {path}: {status} {detail}")
        self.status = status
        self.detail = detail
        self.method = method
        self.path = path


class ArocClient:
    """Sends what the translator produced, to the AROC a config names."""

    def __init__(self, http: HttpClient, config: ReporterConfig) -> None:
        self._http = http
        self._config = config

    def report_step_run(self, intent: ReportStepRun) -> None:
        """Relay what the engine did to one step's run.

        No ids are passed in beside the intent, which is the difference
        from everything this replaced. The intent already names the
        execution and the step, because whatever dispatched the work put
        them where the engine would hand them back.

        `engine_reference` travels on every report. AROC records it on a
        start and ignores it on the others, which is stated on that route
        as the one place it is laxer than its sibling: a reporter
        draining a document stream repeats the engine's own uid on every
        document, and refusing that would make the common case an error.
        """
        path = f"/executions/{intent.execution_id}/steps/{intent.step_id}/run"
        body: dict[str, Any] = {
            "reported": intent.reported,
            "engine_reference": intent.engine_reference,
            "occurred_at": _instant(intent.occurred_at),
        }
        response = self._http.post(self._url(path), json=body, headers=self._headers({}))
        if response.status_code != 204:
            raise RequestRefusedError(response.status_code, response.text, method="POST", path=path)

    def register_dataset(self, intent: RegisterDataset, *, scheme: str) -> UUID:
        """Record where an acquisition's output ended up, and return AROC's id.

        `scheme` is passed in rather than read off the configuration here,
        because it belongs to the optional store table and a client
        reaching into that would have to decide what to do when there is
        none. A caller holding an address necessarily holds the store
        configuration that produced it.

        `occurred_at` is the store's copy of the engine's own ending. It
        travels as `None` when the store holds no ending yet, and AROC
        then stamps the moment it was told, which is honest and less
        precise.
        """
        path = "/datasets"
        body: dict[str, Any] = {
            "execution_id": str(intent.execution_id),
            "step_id": str(intent.step_id),
            "external_ref": {"scheme": scheme, "value": intent.external_ref_value},
            "occurred_at": _instant(intent.occurred_at),
        }
        response = self._http.post(
            self._url(path),
            json=body,
            headers=self._headers({"Idempotency-Key": dataset_key_for(intent.external_ref_value)}),
        )
        if response.status_code != 201:
            raise RequestRefusedError(response.status_code, response.text, method="POST", path=path)
        return UUID(str(response.json()["dataset_id"]))

    def _url(self, path: str) -> str:
        return f"{self._config.base_url}{path}"

    def _headers(self, extra: Mapping[str, str]) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._config.token}", **extra}


def _instant(moment: datetime | None) -> str | None:
    """A timestamp as AROC takes it, or nothing.

    `None` travels rather than being dropped, because the field is
    optional on both commands and sending it explicitly says the delivery
    carried no time. AROC then stamps the moment it was told.
    """
    return None if moment is None else moment.isoformat()


__all__ = [
    "ArocClient",
    "HttpClient",
    "RequestRefusedError",
    "Response",
    "dataset_key_for",
]
