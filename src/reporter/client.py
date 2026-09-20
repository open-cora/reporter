"""The four calls this reporter makes to AROC, and what it does with a no.

The imperative shell on the sending side. It turns an `Intent` into a
request and a response into either an id or a typed refusal, and it holds
no decisions: which plan a name means comes from configuration, which
documents matter comes from the translator.

## Five calls, and the two that are not here

    POST /runs                    a run happened
    POST /runs/{id}/{verb}        a run moved
    POST /datasets                a run produced data, kept over there
    GET  /runs?external_ref=...   which run was that, after a restart
    GET  /plans/{id}              does this configured plan exist

`POST /plans` is deliberately absent. A start document describes one
invocation and carries nothing a correct parameter schema could be derived
from, so an adapter that authors a plan invents a constraint. The
deployment withholds the `DefinePlan` grant as well, which makes this a
refusal at the boundary rather than a rule in a docstring; the absence
here is so nobody has to find that out from a 403.

`GET /plans?name=` is absent for the same reason in reverse. AROC can list
the plans answering to a name but cannot say which one this installation
means, so asking would be asking a question whose answer is in
`ReporterConfig`.

## Redelivery is safe, and the key is why

`report_run` sends an `Idempotency-Key` derived from the engine's own run
id. AROC keys its cache on `(principal_id, key, surface_id)`, so a
restarted reporter recomputes the same key having persisted nothing, and
the second delivery of a start returns the first one's run id rather than
recording a second run. Without the key this is the gap the spike
demonstrated by recording one engine run three times.

`register_dataset` derives its key from the store's address rather than
from the run. The two are the same string today, because one run produces
one dataset, and they part company the moment one produces two: a key
naming the run would give both registrations one note, so the second would
come back holding the first dataset's id and would never be recorded at
all. AROC deliberately did not derive a dataset's identity from its run,
so that one-per-run would not be frozen into the schema, and keying the
retry note on the run would put it back somewhere no migration announces.

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
from reporter.intents import ReportRun, Transition
from reporter.stores import Location


def idempotency_key_for(external_ref_value: str) -> str:
    """The key that makes a redelivered start harmless.

    Derived rather than remembered, which is the whole point. AROC's store
    keys on `(principal_id, key, surface_id)`, so a reporter running as
    one actor recomputes this after any restart having persisted nothing,
    and the second delivery of a start returns the first one's run id
    instead of minting a second record.

    Prefixed because a bare uid in that table says nothing about what it
    was for, and somebody will eventually read the table.

    Here rather than with the translator, where it used to live. Nothing
    about it is an engine's: the prefix and the shape are claims about
    AROC's table, and filing it on the engine side made this module import
    one engine in order to talk to AROC.
    """
    return f"report-run:{external_ref_value}"


def dataset_key_for(external_ref_value: str) -> str:
    """The key that makes a redelivered registration harmless.

    The same trick as above with a different derivation. A start is
    identified by the run it began, so that key names a run; a dataset is
    identified by where the data is, so this one names an address.

    The distinction costs nothing while a run produces one dataset and is
    the whole difference the day it produces two. See the module docstring
    for why naming the run instead would lose the second one silently.
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
        404  the run or plan is not there. configuration, or a lost race.
        409  the run is already in that state. a redelivery, usually
             harmless, and the one refusal a caller should expect.
        422  a key reused with a different body, which means the plan map
             changed underneath an in-flight run.

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

    def report_run(self, intent: ReportRun, plan_id: UUID) -> UUID:
        """Record that a run happened, and return the id AROC gave it.

        `plan_id` is passed in rather than looked up here, because
        resolving it is a refusable decision and a client that resolved it
        silently would be deciding what to do about a name it does not
        recognise.
        """
        path = "/runs"
        body: dict[str, Any] = {
            "plan_id": str(plan_id),
            "parameters": intent.parameters,
            "external_ref": {
                "scheme": self._config.external_ref_scheme,
                "value": intent.external_ref_value,
            },
            "occurred_at": _instant(intent.occurred_at),
        }
        response = self._http.post(
            self._url(path),
            json=body,
            headers=self._headers(
                {"Idempotency-Key": idempotency_key_for(intent.external_ref_value)}
            ),
        )
        if response.status_code != 201:
            raise RequestRefusedError(response.status_code, response.text, method="POST", path=path)
        return UUID(str(response.json()["run_id"]))

    def move_run(self, run_id: UUID, intent: Transition) -> None:
        """Record that a run reached a new state.

        No idempotency key, deliberately. A repeated transition is already
        refused by the aggregate with a 409 naming the state it is in,
        which is a better answer than a cached success: it distinguishes
        a redelivery from a reporter that has lost track of a run.
        """
        path = f"/runs/{run_id}/{intent.verb}"
        response = self._http.post(
            self._url(path),
            json={"occurred_at": _instant(intent.occurred_at)},
            headers=self._headers({}),
        )
        if response.status_code != 204:
            raise RequestRefusedError(response.status_code, response.text, method="POST", path=path)

    def register_dataset(self, run_id: UUID, location: Location, *, scheme: str) -> UUID:
        """Record where a run's output ended up, and return AROC's id for it.

        `scheme` is passed in rather than read off the configuration here,
        because it belongs to the optional store table and a client
        reaching into that would have to decide what to do when there is
        none. A caller holding a location necessarily holds the store
        configuration that produced it.

        `occurred_at` is the store's copy of the engine's own ending. It
        travels as `None` when the store holds no ending yet, and AROC
        then stamps the moment it was told, which is honest and less
        precise.
        """
        path = "/datasets"
        body: dict[str, Any] = {
            "run_id": str(run_id),
            "external_ref": {"scheme": scheme, "value": location.path},
            "occurred_at": _instant(location.occurred_at),
        }
        response = self._http.post(
            self._url(path),
            json=body,
            headers=self._headers({"Idempotency-Key": dataset_key_for(location.path)}),
        )
        if response.status_code != 201:
            raise RequestRefusedError(response.status_code, response.text, method="POST", path=path)
        return UUID(str(response.json()["dataset_id"]))

    def find_run(self, external_ref_value: str) -> UUID | None:
        """The run AROC holds for an engine's run id, if it holds one.

        The recovery a restarted reporter makes, and the reason it needs
        to remember nothing. `None` means AROC has no record, which for a
        transition means the start never arrived.

        A page can hold more than one row, because nothing stops the same
        engine run being recorded twice and AROC shows the duplicate
        rather than hiding it. Taking the first is this reporter's policy
        and it is stated here rather than upstream; a caller that wants to
        know it happened should compare the page length itself.
        """
        path = "/runs"
        response = self._http.get(
            self._url(path),
            params={
                "external_ref_scheme": self._config.external_ref_scheme,
                "external_ref_value": external_ref_value,
            },
        )
        if response.status_code != 200:
            raise RequestRefusedError(response.status_code, response.text, method="GET", path=path)
        items: list[dict[str, Any]] = response.json()["items"]
        if not items:
            return None
        return UUID(str(items[0]["run_id"]))

    def plan_exists(self, plan_id: UUID) -> bool:
        """Whether a configured plan id is one AROC actually holds.

        For the check at startup. A plan map with a typo in it otherwise
        fails on the first run of that plan, at whatever hour that is,
        with a 404 that looks like an AROC problem rather than a
        configuration one.
        """
        path = f"/plans/{plan_id}"
        response = self._http.get(self._url(path))
        if response.status_code == 404:
            return False
        if response.status_code != 200:
            raise RequestRefusedError(response.status_code, response.text, method="GET", path=path)
        return True

    def _url(self, path: str) -> str:
        return f"{self._config.base_url}{path}"

    def _headers(self, extra: Mapping[str, str]) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._config.token}", **extra}


def _instant(moment: datetime | None) -> str | None:
    """A timestamp as AROC takes it, or nothing.

    `None` travels rather than being dropped, because the field is
    optional on every run command and sending it explicitly says the
    document carried no time. AROC then stamps the moment it was told.
    """
    return None if moment is None else moment.isoformat()


__all__ = [
    "ArocClient",
    "HttpClient",
    "RequestRefusedError",
    "Response",
    "dataset_key_for",
    "idempotency_key_for",
]
