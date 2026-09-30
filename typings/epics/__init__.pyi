"""The handful of pyepics calls this project makes, and no more.

pyepics ships neither stubs nor a `py.typed`, so under strict checking
every value that crosses it is unknown and the checking stops at the
boundary. This is that boundary, written narrow on purpose: a list of what
this project depends on rather than a copy of what pyepics offers.

Hand written, and pyright takes it on trust. Nothing here is checked
against the installed package by the type checker, which is what
`test_the_epics_stub_describes_the_package_it_stands_in_for` is for: it
exercises each of these against a live soft IOC and asserts they behave as
declared, so a release that moved a signature fails a test rather than
quietly teaching pyright something untrue.

Two return types are deliberately loose. `PV.get` really does return
whatever the record holds, which is why `EpicsControl` narrows it before
arithmetic. `PV.put` returns 1 on success and None on timeout, which is
why the adapter tests for None rather than for falsehood: a successful put
of the value 0 must not read as a failure.
"""

from typing import Any

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
