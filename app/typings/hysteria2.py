from typing import TypedDict, Literal, List, Dict, Optional, NotRequired
from .common import CommonFields, ListenFields, NamePasswordUser, DailFields
from .tls import Ech, InboundTlsCertificate, OutboundTlsCertificate


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


class Hysteria2(TypedDict):
    up_mbps: NotRequired[int]
    down_mbps: NotRequired[int]
    obfs: Obfs
    tls: InboundTlsCertificate | OutboundTlsCertificate
    brutal_debug: NotRequired[bool]


class InboundHysteria2(CommonFields, ListenFields, Hysteria2):
    users: List[NamePasswordUser]
    ignore_client_bandwidth: bool
    masquerade: NotRequired[MasqueradeConfig]


class OutboundHysteria2(CommonFields, DailFields, Hysteria2):
    password: str


def default_inbound_hy2(
    server_name: str,
    listen_port: int,
    obfs_password: str,
    users: List[NamePasswordUser],
) -> InboundHysteria2:
    return InboundHysteria2(
        type="hysteria2",
        tag="hysteria2",
        listen="0.0.0.0",
        listen_port=listen_port,
        up_mbps=100,
        down_mbps=100,
        obfs=Obfs(
            type="salamander",
            password=obfs_password,
        ),
        users=[
            NamePasswordUser(
                name=name,
                password=password,
            )
            for name, password in users
        ],
        ignore_client_bandwidth=True,
        tls=InboundTlsCertificate(
            enabled=True,
            server_name=server_name,
            alpn=["h3"],
            min_version="1.3",
            max_version="1.3",
            key_path="certs/private.key",
            certificate_path="certs/cert.pem",
            ech=Ech(
                enabled=True,
                key_path="certs/ech_private.key",
            ),
        ),
    )


def default_outbound_hy2(
    server_name: str,
    server_port: int,
    obfs_password: str,
) -> OutboundHysteria2:
    return OutboundHysteria2(
        type="hysteria2",
        tag="hysteria2",
        server=server_name,
        server_port=server_port,
        obfs=Obfs(
            type="salamander",
            password=obfs_password,
        ),
        password="",
        tls=OutboundTlsCertificate(
            enabled=True,
            certificate=[],
            ech=Ech(
                enabled=True,
                config=[],
            ),
        ),
    )


def in_out():
    pass