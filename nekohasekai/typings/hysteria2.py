from typing import TypedDict, Literal, List, Dict, Any, Optional, NotRequired
from typings.common import CommonFields, ListenFields, NamePasswordUser, DailFields
from typings.tls import InboundTlsCertificate, InboundTlsReality, OutboundTlsCertificate


class Obfs(TypedDict):
    type: Literal["salamander"]
    password: str


class MasqueradeConfig(TypedDict):
    type: Literal["file", "proxy", "string"]
    directory: Optional[str]  # if type is file
    url: Optional[str]  # if type is proxy
    rewrite_host: Optional[str]
    status_code: Optional[int]  # if type is string
    headers: Optional[Dict[str, str]]
    content: Optional[str]


class InboundHysteria2(CommonFields, ListenFields):
    up_mbps: int
    down_mbps: int
    obfs: Obfs
    users: List[NamePasswordUser]
    ignore_client_bandwidth: bool
    tls: InboundTlsCertificate | InboundTlsReality
    masquerade: NotRequired[MasqueradeConfig] | Dict[str, Any]
    brutal_debug: bool


class OutboundHysteria2(CommonFields, DailFields):
    up_mbps: int
    down_mbps: int
    obfs: Obfs
    password: str
    tls: OutboundTlsCertificate
    brutal_debug: bool
