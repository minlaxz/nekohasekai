from typing import TypedDict, NotRequired, Literal, List, Optional


class Handshake(TypedDict):
    server: str
    server_port: int


class InboundReality(TypedDict):
    enabled: bool
    private_key: str
    short_id: List[str | None]
    handshake: Handshake


class Tls(TypedDict):
    enabled: bool
    server_name: str
    alpn: NotRequired[List[str]]
    min_version: NotRequired[Literal["1.3", "1.2", "1.1", "1.0"]]
    max_version: NotRequired[Literal["1.3", "1.2", "1.1", "1.0"]]


class InboundTlsReality(Tls):
    reality: InboundReality


class InboundTlsCertificate(Tls):
    key_path: str
    certificate_path: str


class Utls(TypedDict):
    enabled: bool
    fingerprint: Literal["chrome", "firefox", "safari", "edge"]


class OutboundReality(TypedDict):
    enabled: bool
    public_key: str
    short_id: str


class OutboundTlsReality(Tls):
    utls: Utls
    reality: OutboundReality


class OutboundTlsCertificate(Tls):
    certificate: List[str]
    insecure: bool
    utls: Optional[Utls]
