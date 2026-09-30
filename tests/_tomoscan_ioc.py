#!/usr/bin/env python3
"""A soft IOC shaped like TomoScan, for driving the record source against.

Smaller than the conductor's, because this side only reads. It serves the
five records the source watches and one switch that ends a scan, which is
all the source needs to see a transition.

Run it as a script rather than with `-m`: `tests/` is on the path pytest
builds and not on a fresh interpreter's.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from caproto import ChannelType
from caproto.server import PVGroup, pvproperty, run

SERVER_PORT = 5095
"""A port of this fixture's own, so it never collides with a real IOC.

caproto reads `EPICS_CA_SERVER_PORT` and ignores the `EPICS_CAS_` spelling,
which is worth knowing: setting the other leaves the server on the default
port and answering for a prefix somebody else may be using.
"""

CLIENT_ADDR_LIST = f"127.0.0.1:{SERVER_PORT}"
PREFIX = "reporter-tomoscan-test:"
IDLE = "Done"
BUSY = "Scan"


def _text(value: str, size: int = 256) -> Any:
    """A character waveform, which is how TomoScan serves its strings."""
    return pvproperty(
        value=value,
        dtype=ChannelType.CHAR,
        max_length=size,
        report_as_string=True,
        string_encoding="utf-8",
    )


class TomoscanIOC(PVGroup):
    """Only the records the source reads, plus the one it watches for."""

    StartScan = pvproperty(value=IDLE, enum_strings=[IDLE, BUSY], dtype=ChannelType.ENUM)
    ScanStatus = _text("Scan complete")
    FullFileName = _text("")
    KeeperExecutionId = _text("")
    KeeperStepId = _text("")


def start() -> subprocess.Popen[bytes]:
    """Serve the records, and hand back the process serving them."""
    return subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--prefix", PREFIX],
        env={**os.environ, **server_environment()},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def server_environment() -> dict[str, str]:
    """Keep this IOC on the loopback and on a port of its own."""
    return {
        "EPICS_CA_ADDR_LIST": CLIENT_ADDR_LIST,
        "EPICS_CA_AUTO_ADDR_LIST": "NO",
        "EPICS_CAS_BEACON_ADDR_LIST": "127.0.0.1",
        "EPICS_CAS_AUTO_BEACON_ADDR_LIST": "NO",
        "EPICS_CA_SERVER_PORT": str(SERVER_PORT),
    }


def wait_until_serving(server: subprocess.Popen[bytes], timeout: float) -> None:
    """Block until the IOC answers a search, or say why it never did."""
    import epics

    started = epics.PV(f"{PREFIX}{'StartScan'}")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if server.poll() is not None:
            raise RuntimeError(f"the TomoScan IOC exited with {server.returncode} before serving")
        if started.wait_for_connection(timeout=0.2):
            return
    raise RuntimeError(f"the TomoScan IOC did not answer for {PREFIX}StartScan in {timeout:g}s")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", required=True)
    arguments = parser.parse_args()
    run(TomoscanIOC(prefix=arguments.prefix).pvdb, log_pv_names=False)


if __name__ == "__main__":
    main()
