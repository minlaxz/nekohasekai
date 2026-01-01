from typing import TypedDict, NotRequired, Literal, List


class Tls(TypedDict):
    enabled: bool
    alpn: NotRequired[List[str]]
    min_version: NotRequired[Literal["1.3", "1.2", "1.1", "1.0"]]
    max_version: NotRequired[Literal["1.3", "1.2", "1.1", "1.0"]]


class Ech(TypedDict):
    enabled: bool
    key: NotRequired[List[str]]
    key_path: NotRequired[str]
    config: NotRequired[List[str]]
    config_path: NotRequired[str]


class Handshake(TypedDict):
    server: str
    server_port: int
    domain_strategy: str


class InboundReality(TypedDict):
    enabled: bool
    private_key: str
    short_id: List[str | None]
    handshake: Handshake


class InboundTlsCertificate(Tls):
    server_name: str
    key_path: str
    certificate_path: str
    ech: NotRequired[Ech]
    reality: NotRequired[InboundReality]


class Utls(TypedDict):
    enabled: bool
    fingerprint: Literal["chrome", "firefox", "safari", "edge"]


class OutboundReality(TypedDict):
    enabled: bool
    public_key: str
    short_id: str


class OutboundTlsCertificate(Tls):
    server_name: NotRequired[str]
    certificate: NotRequired[List[str]]
    utls: NotRequired[Utls]
    ech: NotRequired[Ech]
    reality: NotRequired[OutboundReality]
