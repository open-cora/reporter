"""The thread-context corner of pyepics, which the record source needs.

pyepics binds a Channel Access context per thread, and a channel opened
in one is unusable from another. A reader running in its own thread has
to join the context the main thread made before it touches a PV.
"""

def use_initial_context() -> None: ...

class ChannelAccessException(Exception):  # noqa: N818
    """What a read raises when its context has gone rather than answering.

    A reader thread outliving the server it polls is ordinary in a test,
    and this is how pyepics reports it. Catching it by type rather than
    broadly is what keeps a source failing some other way visible.

    The name is pyepics' and cannot be the Error one this project's
    naming rule asks for, because a stub describes a library rather
    than declaring one.
    """
