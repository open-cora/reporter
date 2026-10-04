"""A stub for the part of caproto the soft IOC in `tests` uses.

Hand-written because caproto ships no types and its server API is built
out of descriptors that a generated stub models badly. The surface here
is four names wide, which is the whole of what a double needs.

`pvproperty` is deliberately `Any`. It is a descriptor whose attribute
access yields a different type per declared record, and whose `putter`
re-binds the same name to a coroutine. Modelling that faithfully would
cost more than the double it serves, and every use of it in this project
is a test helper rather than shipped code.
"""

from enum import IntEnum

class ChannelType(IntEnum):
    STRING = 0
    INT = 1
    FLOAT = 2
    ENUM = 3
    CHAR = 4
    LONG = 5
    DOUBLE = 6
