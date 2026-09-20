"""The two calls this project makes into msgpack, and no more.

msgpack ships neither stubs nor a `py.typed`, so under strict checking
every value that passes through it is unknown and the checking stops at
the boundary. This is that boundary, written narrow on purpose: a list of
what this project depends on rather than a copy of what msgpack offers.

Hand written, and pyright takes it on trust. Nothing here is checked
against the installed package by the type checker, which is what
`test_the_msgpack_stub_describes_the_package_it_stands_in_for` is for: it
calls both of these and asserts they behave as declared, so a release that
moved either signature fails a test rather than quietly teaching pyright
something untrue.

`unpackb` really does return whatever was encoded, which is why
`sources.decode` checks the shape of what comes back before trusting it.
"""

from typing import Any

def packb(o: Any, /, **kwargs: Any) -> bytes: ...
def unpackb(packed: bytes, /, **kwargs: Any) -> Any: ...

dumps = packb
loads = unpackb
