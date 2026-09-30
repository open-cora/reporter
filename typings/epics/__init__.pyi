"""The handful of pyepics calls this project makes, and no more.

pyepics ships neither stubs nor a `py.typed`, so under strict checking
every value that crosses it is unknown and the checking stops at the
boundary. This is that boundary, written narrow on purpose: a list of what
this project depends on rather than a copy of what pyepics offers.

Hand written, and pyright takes it on trust. Nothing here is checked
against the installed package by the type checker, so a release that moved
a signature would quietly teach pyright something untrue. What catches
that in this project is `test_a_scan_returning_to_idle_is_what_the_source_reacts_to`,
which drives every name below against a live soft IOC. That is a weaker
guard than a test written for the purpose, because it exercises these
calls on its way to something else and would report a moved signature as a
source that stopped working. It is named here so the next reader knows
which it is.

Two return types are deliberately loose. `PV.get` really does return
whatever the record holds, which is why a caller narrows it before
arithmetic. `PV.put` returns 1 on success and None on timeout, which is
why a caller tests for None rather than for falsehood: a successful put
of the value 0 must not read as a failure.
"""

from typing import Any

from . import ca as ca

class PV:
    pvname: str
    def __init__(
        self,
        pvname: str,
        /,
        *,
        connection_timeout: float | None = ...,
    ) -> None: ...
    def wait_for_connection(self, timeout: float | None = ...) -> bool: ...
    def get(
        self,
        *,
        as_string: bool = ...,
        timeout: float | None = ...,
        use_monitor: bool = ...,
    ) -> Any: ...
    def put(
        self,
        value: Any,
        /,
        *,
        wait: bool = ...,
        timeout: float = ...,
    ) -> int | None: ...
    def disconnect(self) -> None: ...

def caput(
    pvname: str,
    value: Any,
    /,
    *,
    wait: bool = ...,
    timeout: float = ...,
) -> int | None: ...
def caget(
    pvname: str,
    /,
    *,
    as_string: bool = ...,
    timeout: float = ...,
) -> Any: ...
