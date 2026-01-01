from typing import TypedDict, NotRequired, Literal, Dict


class Listen(TypedDict, total=False):
    tcp_fast_open: NotRequired[bool]
    tcp_multi_path: NotRequired[bool]
    routing_mark: NotRequired[int]
    udp_fragment: NotRequired[bool]
    detour: NotRequired[str]


class Dail(Listen):
    pass


class CommonFields(TypedDict):
    tag: str
    type: Literal[
        "direct",
        "shadowsocks",
        "ssm-api",
        "trojan",
        "hysteria2",
        "shadowtls",
    ]


class ListenFields(Listen):
    listen: Literal["0.0.0.0", "::", "127.0.0.1"]
    listen_port: NotRequired[int]
    udp_timeout: NotRequired[str]


class DailFields(Dail):
    server: NotRequired[str]
    server_port: NotRequired[int]
    connect_timeout: NotRequired[str]
    network_type: NotRequired[Literal["wifi", "cellular", "ethernet", "other"]]
    fallback_network_type: NotRequired[Literal["wifi", "cellular", "ethernet", "other"]]
    fallback_delay: NotRequired[str]
    network_strategy: NotRequired[Literal["default", "hybrid", "fallback"]]


class NamePasswordUser(TypedDict):
    name: str
    password: str


class SSMService(CommonFields, ListenFields):
    cache_path: str
    servers: Dict[str, str]


class UoT(TypedDict):
    enabled: bool
    version: NotRequired[Literal[1, 2]]


class DomainResolver(TypedDict):
    server: str
    strategy: Literal["ipv4_only", "prefer_ipv4"]
