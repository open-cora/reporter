"""Stand-ins that record instead of sending.

Two HTTP clients, because the two suites want opposite things. `Recorder`
answers in the order it was given, which is what a test asserting on one
request wants. `Routed` answers by which call was made, which is what a
test feeding a whole captured scenario wants, since the number of requests
then depends on the documents rather than on the test.

`Store` is the third, and it stands in for the other outside system rather
than for AROC.

None of them models what it replaces. They return what they were told to
return, so a test that wants a 409 has to say so. A fake that decided for
itself when to conflict would be a second implementation of the aggregate,
drifting from the real one with nothing comparing them.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from reporter.stores import Location


@dataclass(frozen=True)
class Sent:
    """One request, as the client built it."""

    method: str
    url: str
    params: Mapping[str, str] | None = None
    json: Mapping[str, Any] | None = None
    headers: Mapping[str, str] | None = None


@dataclass(frozen=True)
class Answer:
    """One canned response."""

    status_code: int
    payload: Any = None
    text: str = ""

    def json(self) -> Any:
        return self.payload


@dataclass
class Recorder:
    """Answers in order, and remembers what it was asked.

    Running out of answers raises, deliberately: a test whose client made
    more calls than it scripted has found something, and a fake that
    padded with a default would hide it.
    """

    answers: list[Answer]
    sent: list[Sent] = field(default_factory=list["Sent"])

    def get(self, url: str, *, params: Mapping[str, str] | None = None) -> Answer:
        self.sent.append(Sent("GET", url, params=params))
        return self.answers.pop(0)

    def post(
        self,
        url: str,
        *,
        json: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Answer:
        self.sent.append(Sent("POST", url, json=json, headers=headers))
        return self.answers.pop(0)


@dataclass
class Routed:
    """Answers by which call was made, not by how many have been.

    The two slots are the two calls `KeeperClient` makes once a store is
    configured. Each holds a list consumed in order and reused once
    exhausted, so a scenario of any length needs one entry, and a test
    wanting the second report refused supplies two.

    It held four before. The two that went were a run's genesis and the
    lookup that found a run again, and both went for the same reason:
    AROC dispatches the work, so there is nothing for this reporter to
    create and nothing for it to resolve.
    """

    report: list[Answer] = field(default_factory=list["Answer"])
    register: list[Answer] = field(default_factory=list["Answer"])
    sent: list[Sent] = field(default_factory=list["Sent"])

    def get(self, url: str, *, params: Mapping[str, str] | None = None) -> Answer:
        """Recorded and then refused, because nothing should call it.

        This reporter makes no GET against AROC any more. Keeping the
        method on the fake is what makes that assertable: a test can show
        the client satisfies the `HttpClient` protocol and still never
        reads.
        """
        self.sent.append(Sent("GET", url, params=params))
        raise AssertionError(f"This reporter does not read from AROC, and something asked {url}.")

    def post(
        self,
        url: str,
        *,
        json: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Answer:
        self.sent.append(Sent("POST", url, json=json, headers=headers))
        # A registration posts to /datasets and an engine report to
        # /executions/<id>/steps/<id>/run, which is not that.
        trimmed = url.rstrip("/")
        return self._next(self.register if trimmed.endswith("/datasets") else self.report)

    def calls(self, method: str, *, containing: str = "") -> list[Sent]:
        """Every recorded call matching a method, and optionally a path."""
        return [s for s in self.sent if s.method == method and containing in s.url]

    @staticmethod
    def _next(answers: list[Answer]) -> Answer:
        if not answers:
            raise AssertionError("A call was made that this fake has no answer for.")
        return answers.pop(0) if len(answers) > 1 else answers[0]


@dataclass
class Store:
    """A store that holds whatever the test put in it.

    Keyed by the engine's run id, which is what a lookup is given. A uid
    with no entry answers `None`, the way a real store answers for a run
    it was never handed, and `asked` is there so a test can show the leg
    did not run rather than inferring it from the absence of a request.
    """

    locations: dict[str, Location] = field(default_factory=dict["str", "Location"])
    refusal: Exception | None = None
    asked: list[str] = field(default_factory=list["str"])

    def locate(self, run_uid: str) -> Location | None:
        self.asked.append(run_uid)
        if self.refusal is not None:
            raise self.refusal
        return self.locations.get(run_uid)


__all__ = ["Answer", "Recorder", "Routed", "Sent", "Store"]
