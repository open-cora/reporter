"""Session setup that has to happen before anything touches Channel Access.

## Why this file exists

The suite passed and the process then died with a segmentation fault, after
pytest had printed its summary and before the shell got its exit code. `make
test` returned 139 and the run reported no failing test, which is the shape of
a crash in a C extension during interpreter shutdown rather than a defect any
test can point at. It reproduced about one run in five, on a developer machine
and on a CI runner alike.

`PYTHONFAULTHANDLER=1` named it exactly. The main thread was inside pyepics'
`finalize_libca`, clearing channels. A reader thread started by
`test_tomoscan_records` was inside `PV.get()` on one of them. Freeing a channel
while another thread reads it is a use after free, and the race is only ever
lost at exit, which is why no test could see it.

## What this does about it

`epics.ca.AUTO_CLEANUP` is pyepics' own switch for this. Left true, importing
and initializing the library registers `finalize_libca` with `atexit`; set
false before the library initializes, the handler is never registered and the
teardown that loses the race never runs.

Skipping it costs nothing here. The handler releases sockets and contexts
belonging to a process that is exiting anyway, and the operating system
reclaims every one of them. What it buys is that a reader thread outliving its
test can no longer be reading a channel while something frees it.

## Why not join the threads instead

That was tried first and does not work. A reader polls a generator that does
not end, and the documented claim that it dies when the IOC goes away is not
borne out: after the server is terminated the reads time out and return
nothing rather than raising, so the thread keeps polling. Waiting for the
readers added thirty seconds to the module and still left them running.
"""

from __future__ import annotations

try:
    import epics.ca
except ImportError:
    pass
else:
    epics.ca.AUTO_CLEANUP = False
