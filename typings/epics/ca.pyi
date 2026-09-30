"""The thread-context corner of pyepics, which the record source needs.

pyepics binds a Channel Access context per thread, and a channel opened
in one is unusable from another. A reader running in its own thread has
to join the context the main thread made before it touches a PV.
"""

def use_initial_context() -> None: ...
