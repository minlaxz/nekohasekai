from typing import TypedDict, List, Dict
from .common import CommonFields


class WireguardPeer(TypedDict):
    public_key: str
    allowed_ips: List[str]


class WireguardEndpoint(CommonFields):
    name: str
    system: bool
    mtu: int
    address: List[str]
    private_key: str
    listen_port: int
    peers: List[WireguardPeer]


class WireguardKeys(TypedDict):
    tag: str
    keys: Dict[str, str]  # = field(default_factory=dict[str, str])
