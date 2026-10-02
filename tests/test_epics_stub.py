"""The stub says what this app uses of pyepics, and this says it is true.

`typings/epics/` is hand written, so pyright checks the record source
against a description of the library rather than against the library.
A name the stub claims and pyepics does not have passes the type check
and fails at a beamline, which is the wrong order.
"""

from __future__ import annotations

import pytest


@pytest.mark.channel_access
def test_the_exception_a_lost_context_raises_is_the_one_the_stub_names() -> None:
    import epics

    assert issubclass(epics.ca.ChannelAccessException, Exception), (
        "the record source's test harness catches this by type, so a "
        "pyepics that spells it differently would turn a torn-down "
        "context back into an unexplained traceback"
    )
