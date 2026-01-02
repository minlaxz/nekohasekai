from typing import NotRequired, TypedDict, Optional, Literal


class Brutal(TypedDict):
    enabled: bool
    up_mbps: Optional[int]
    down_mbps: Optional[int]


class Multiplex(TypedDict, total=False):
    enabled: bool
    padding: bool
    brutal: NotRequired[Brutal]


class InboundMultiplex(Multiplex):
    pass


class OutboundMultiplex(Multiplex):
    protocol: Literal["smux", "yamux", "h2mux"]
    max_connections: int
    min_streams: int
    max_streams: int


# __all__ = [
#     "InboundMultiplex",
#     "OutboundMultiplex",
#     "Brutal",
# ]