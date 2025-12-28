from typing import TypedDict, NotRequired, List, Literal, Dict
from typings.common import CommonFields, ListenFields, DailFields
from typings.multiplex import InboundMultiplex, OutboundMultiplex


class Shadowsocks(TypedDict):
    method: Literal["xchacha20-ietf-poly1305", "chacha20-ietf-poly1305"]
    password: str
    multiplex: NotRequired[InboundMultiplex | OutboundMultiplex]


class ShadowsocksUser(TypedDict):
    password: str
    method: str


class InboundShadowsocks(CommonFields, ListenFields, Shadowsocks):
    users: NotRequired[List[ShadowsocksUser]]
    managed: bool
    network: NotRequired[Literal["tcp", "udp"]]


class OutboundShadowsocks(CommonFields, DailFields, Shadowsocks):
    udp_over_tcp: NotRequired[Dict[str, bool | int]]
