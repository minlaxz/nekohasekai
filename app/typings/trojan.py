from typing import List, NotRequired, Literal, TypedDict
from .common import CommonFields, ListenFields, NamePasswordUser, DailFields
from .multiplex import InboundMultiplex, OutboundMultiplex
from .tls import InboundTlsCertificate, OutboundTlsCertificate, Ech


class Trojan(TypedDict):
    tls: InboundTlsCertificate | OutboundTlsCertificate
    multiplex: NotRequired[InboundMultiplex | OutboundMultiplex]


class InboundTrojan(CommonFields, ListenFields, Trojan):
    users: List[NamePasswordUser]


class OutboundTrojan(CommonFields, DailFields, Trojan):
    password: str
    network: NotRequired[Literal["tcp", "udp"]]


def default_inbound_tj(
    server_name: str,
    listen_port: int,
    users: List[NamePasswordUser],
) -> InboundTrojan:
    return InboundTrojan(
        type="trojan",
        tag="trojan",
        listen="0.0.0.0",
        listen_port=listen_port,
        users=[
            NamePasswordUser(
                name=user,
                password=password,
            )
            for user, password in users
        ],
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
        multiplex=InboundMultiplex(enabled=True, padding=False),
    )


def default_outbound_tj(server_name: str, server_port: int) -> OutboundTrojan:
    with open("certs/cert.pem", "r") as cert_file:
        certificate_array = [line.rstrip("\n") for line in cert_file]

    with open("certs/ech_public.key", "r") as ech_file:
        ech_config_array = [line.rstrip("\n") for line in ech_file]

    return OutboundTrojan(
        type="trojan",
        tag="trojan",
        server=server_name,
        server_port=server_port,
        password="",
        tls=OutboundTlsCertificate(
            enabled=True,
            alpn=["h3"],
            min_version="1.3",
            max_version="1.3",
            certificate=certificate_array,
            ech=Ech(
                enabled=True,
                config=ech_config_array,
            ),
        ),
        multiplex=OutboundMultiplex(
            protocol="h2mux",
            enabled=True,
            padding=False,
            max_connections=1,
            min_streams=4,
            max_streams=8,
        ),
    )
