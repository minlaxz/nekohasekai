from typing import Literal, List, Dict, Tuple
from .common import CommonFields, ListenFields, DailFields
from .tls import Handshake, OutboundTlsCertificate
from .common import NamePasswordUser
from .shadowsocks import InboundShadowsocks, OutboundShadowsocks


class InboundShadowTLS(CommonFields, ListenFields):
    version: Literal[1, 2, 3]
    users: List[NamePasswordUser]
    handshake: Handshake


class OutboundShadowTLS(CommonFields, DailFields):
    version: Literal[1, 2, 3]
    password: str
    tls: OutboundTlsCertificate


def default_inbound_stls(
    listen_port: int,
    users: List[Dict[str, str]],
    handshake_domain: str,
    handshake_port: int,
    ss_password: str,
) -> Tuple[InboundShadowsocks, InboundShadowTLS]:
    _ss = InboundShadowsocks(
        type="shadowsocks",
        tag="ss-in",
        listen="127.0.0.1",
        method="xchacha20-ietf-poly1305",
        password=ss_password,
        managed=False,
        network="tcp",
    )
    _stls = InboundShadowTLS(
        type="shadowtls",
        tag="shadowtls",
        listen="0.0.0.0",
        listen_port=listen_port,
        detour=_ss["tag"],
        version=3,
        users=[
            NamePasswordUser(
                name=name,
                password=password,
            )
            for name, password in users
        ],
        handshake=Handshake(
            server=handshake_domain,
            server_port=handshake_port,
            domain_strategy="ipv4_only",
        ),
    )
    return _ss, _stls


def default_outbound_stls(
    server_ip: str,
    server_port: int,
    ss_password: str,
) -> Tuple[OutboundShadowTLS, OutboundShadowsocks]:
    _stls = OutboundShadowTLS(
        type="shadowtls",
        tag="shadowtls-exp",
        server=server_ip,
        server_port=server_port,
        version=3,
        password="",
        tls=OutboundTlsCertificate(
            enabled=True,
            server_name="",
        ),
    )
    _ss = OutboundShadowsocks(
        type="shadowsocks",
        tag="ss-out-exp",
        detour=_stls["tag"],
        method="xchacha20-ietf-poly1305",
        password=ss_password,
        udp_over_tcp={
            "enabled": True,
            "version": 2,
        },  # version 1.11.4 users need version 1
    )
    return _stls, _ss
