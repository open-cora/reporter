"""The process can start on the libraries its deployment actually installs.

Every adapter's library is an extra, and the deploy script passes two of
them: `--extra service` and `--extra epics`. So a beamline reporter runs
with no pyzmq and no msgpack, and anything the entrypoint imports along
the way has to hold under that.

It did not. `python -m reporter` imported the subscription adapter
whichever source was configured, that adapter imported both libraries at
its top, and the process raised `ModuleNotFoundError: msgpack` before
parsing an argument. Nothing caught it: the suite installs the dev group,
which carries every library, so the one environment where it fails is the
only one not tested.

The failure is also invisible until a restart, which is the worst
property it could have. A reporter already running keeps running, so the
break lands on whoever next deploys or reboots a beamline host.

## Why the import is blocked rather than the environment rebuilt

Building a second virtualenv per run would be minutes of wheels to prove
one import, and pyepics does not install from a wheel everywhere. A meta
path finder that refuses two names reproduces exactly the condition that
matters, which is that the import fails, and runs in milliseconds.
"""

from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import Generator
    from types import ModuleType

EXTRA_LIBRARIES: dict[str, tuple[str, ...]] = {
    "subscribe": ("zmq", "msgpack"),
    "epics": ("epics",),
}
"""Which libraries a deployment is NOT obliged to install, by extra.

Read against `pyproject.toml`, where each of these is an optional
dependency, and against `infra/deploy/install.sh`, which passes `service`
and `epics` and never `subscribe`.
"""

ENTRYPOINT = "reporter.__main__"


class _Blocker:
    """Refuses a set of top-level imports, as an absent library would."""

    def __init__(self, absent: frozenset[str]) -> None:
        self._absent = absent

    def find_spec(self, name: str, path: Any = None, target: Any = None) -> None:
        _ = path, target
        if name.split(".")[0] in self._absent:
            raise ModuleNotFoundError(f"No module named {name!r}")
        return None


@contextmanager
def _without(*libraries: str) -> Generator[None]:
    absent = frozenset(libraries)
    evicted = {
        name: module
        for name, module in sys.modules.items()
        if name.split(".")[0] in absent or name.startswith("reporter")
    }
    for name in evicted:
        del sys.modules[name]
    blocker = _Blocker(absent)
    sys.meta_path.insert(0, blocker)
    try:
        yield
    finally:
        sys.meta_path.remove(blocker)
        for name in list(sys.modules):
            if name.startswith("reporter"):
                del sys.modules[name]
        sys.modules.update(evicted)


def _imported(module: str) -> ModuleType:
    return importlib.import_module(module)


def test_the_entrypoint_imports_without_the_subscribe_extra() -> None:
    """The one a real deployment is missing, and the one that broke."""
    with _without(*EXTRA_LIBRARIES["subscribe"]):
        assert _imported(ENTRYPOINT) is not None


def test_asking_for_a_subscription_without_its_libraries_says_which_extra() -> None:
    """A deployment that genuinely wants one gets told how, not a traceback."""
    with _without(*EXTRA_LIBRARIES["subscribe"]):
        adapter = _imported("reporter.adapters.zmq_subscription")
        with pytest.raises(ImportError, match="subscribe"):
            next(iter(adapter.from_subscription("tcp://127.0.0.1:5568")))


def test_the_decoder_still_refuses_a_frame_it_cannot_read_without_the_libraries() -> None:
    """The error the entrypoint catches has to exist without the extra.

    `drive` catches `DecodeError`, so the class is reached on every run
    whether or not anything subscribes. A fix that moved the class behind
    the import would pass the test above and break the same deployment
    one line further on.
    """
    with _without(*EXTRA_LIBRARIES["subscribe"]):
        adapter = _imported("reporter.adapters.zmq_subscription")
        assert issubclass(adapter.DecodeError, Exception)
