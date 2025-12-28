from typings.trojan import InboundTrojan, OutboundTrojan, NamePasswordUser
from typings.tls import InboundTLSCertificate
from typings.multiplex import InboundMultiplex, OutboundMultiplex, Brutal
from typings.tls import ClientTLSInsecure, Utls
from common import InboundsConfig, ClientOutboundsConfig

def generate(
    trojan_listen_port: int,
    trojan_password: str,
    handshake_domain: str,
    server_ip: str,
    inbounds_config: InboundsConfig,
    client_outbounds_config: ClientOutboundsConfig,
):
    inbound_trojan = InboundTrojan(
        type="trojan",
        tag="trojan",
        listen="0.0.0.0",
        listen_port=trojan_listen_port,
        users=[
            NamePasswordUser(
                name="user",
                password=trojan_password,
            ),
        ],
        tls=InboundTLSCertificate(
            enabled=True,
            server_name=handshake_domain,
            alpn=["h2", "http/1.1"],
            min_version="1.2",
            max_version="1.3",
            key_path="certs/private.key",
            certificate_path="certs/cert.pem",
        ),
        multiplex=InboundMultiplex(enabled=True, padding=False),
    )
    outbound_trojan = OutboundTrojan(
        type="trojan",
        tag="trojan",
        server=server_ip,
        server_port=trojan_listen_port,
        network="tcp",
        password=trojan_password,
        tls=ClientTLSInsecure(
            enabled=True,
            server_name=handshake_domain,
            alpn=["h2", "http/1.1"],
            min_version="1.2",
            max_version="1.3",
            insecure=True,
            utls=Utls(
                enabled=True,
                fingerprint="chrome",
            ),
        ),
        multiplex=OutboundMultiplex(
            protocol="h2mux",
            enabled=True,
            padding=False,
            max_connections=1,
            min_streams=4,
            max_streams=8,
            brutal=Brutal(enabled=False, up_mbps=0, down_mbps=0),
        ),
    )
    inbounds_config.inbounds.append(inbound_trojan)
    client_outbounds_config.outbounds.append(outbound_trojan)
