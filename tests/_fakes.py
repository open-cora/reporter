"""HTTP clients that record instead of sending.

Two of them, because the two suites want opposite things. `Recorder`
answers in the order it was given, which is what a test asserting on one
request wants. `Routed` answers by which of the three calls was made,
which is what a test feeding a whole captured scenario wants, since the
number of requests then depends on the documents rather than on the test.

Neither models AROC. They return what they were told to return, so a test
that wants a 409 has to say so. A fake that decided for itself when to
conflict would be a second implementation of the aggregate, drifting from
the real one with nothing comparing them.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


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

    The three slots are the three calls `ArocClient` makes against runs.
    Each holds a list consumed in order and reused once exhausted, so a
    scenario of any length needs one entry, and a test wanting the second
    transition refused supplies two.
    """

    report: list[Answer]
    move: list[Answer]
    find: list[Answer] = field(default_factory=list["Answer"])
    sent: list[Sent] = field(default_factory=list["Sent"])

    def get(self, url: str, *, params: Mapping[str, str] | None = None) -> Answer:
        self.sent.append(Sent("GET", url, params=params))
        return self._next(self.find)

    def post(
        self,
        url: str,
        *,
        json: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Answer:
        self.sent.append(Sent("POST", url, json=json, headers=headers))
        # A transition posts to /runs/<id>/<verb>; a report posts to /runs.
        reporting = url.rstrip("/").endswith("/runs")
        return self._next(self.report if reporting else self.move)

    def calls(self, method: str, *, containing: str = "") -> list[Sent]:
        """Every recorded call matching a method, and optionally a path."""
        return [s for s in self.sent if s.method == method and containing in s.url]

    @staticmethod
    def _next(answers: list[Answer]) -> Answer:
        if not answers:
            raise AssertionError("A call was made that this fake has no answer for.")
        return answers.pop(0) if len(answers) > 1 else answers[0]


__all__ = ["Answer", "Recorder", "Routed", "Sent"]
