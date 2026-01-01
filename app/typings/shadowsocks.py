from typing import Dict, Tuple, TypedDict, NotRequired, List, Literal
from .common import CommonFields, ListenFields, DailFields, UoT
from .multiplex import InboundMultiplex, OutboundMultiplex


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
    udp_over_tcp: NotRequired[UoT]


class SSMService(CommonFields, ListenFields):
    cache_path: str
    servers: Dict[str, str]


def ss_inbound(
    managed: bool = True,
    port: int = 0,
    ssm_port: int = 0,
) -> Tuple[InboundShadowsocks, SSMService]:
    """shadowsocks inbound config

    Args:
        managed (bool, optional): Whether the inbound connection is managed. Defaults to True.
        port (int, optional): The port number to listen on. Defaults to 0.

    Returns:
        InboundShadowsocks: The configured inbound Shadowsocks object.
    """
    ssm_service = SSMService(
        type="ssm-api",
        tag="ssm-api",
        listen="0.0.0.0",
        listen_port=ssm_port,
        cache_path="cache/ssm-cache.json",
        servers={"/": "shadowsocks"},
    )
    ss_in = InboundShadowsocks(
        type="shadowsocks",
        tag="shadowsocks",
        listen="0.0.0.0",
        listen_port=port,
        method="xchacha20-ietf-poly1305",
        password="",
        users=[],
        managed=managed,
        multiplex=InboundMultiplex(enabled=True, padding=False),
    )
    return ss_in, ssm_service


def ss_outbound(server_ip: str, port: int) -> OutboundShadowsocks:
    """shadowsocks outbound config
    Args:
        server_ip (str): The server IP address to connect to.
        port (int): The server port number to connect to.
    Returns:
        OutboundShadowsocks: The configured outbound Shadowsocks object.
    """
    return OutboundShadowsocks(
        type="shadowsocks",
        tag="shadowsocks-out",
        server=server_ip,
        server_port=port,
        method="xchacha20-ietf-poly1305",
        password="",
        udp_over_tcp=UoT(
            enabled=True,
            version=2,
        ),
        multiplex=OutboundMultiplex(
            enabled=True,
            protocol="h2mux",
            padding=False,
            max_connections=2,
            min_streams=4,
            max_streams=8,
        ),
    )
