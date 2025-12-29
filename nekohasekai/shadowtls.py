from typings.common import NamePasswordUser
from typings.tls import Handshake, Utls, OutboundTlsCertificate
from typings.shadowtls import InboundShadowTLS, OutboundShadowTLS
from typings.shadowsocks import InboundShadowsocks, OutboundShadowsocks
from common import InboundsConfig, ClientOutboundsConfig


def generate(
    shadowtls_listen_port: int,
    shadowtls_password: str,
    handshake_domain: str,
    server_ip: str,
    inbounds_config: InboundsConfig,
    client_outbounds_config: ClientOutboundsConfig,
):
    inbound_shadowtls = InboundShadowTLS(
        type="shadowtls",
        tag="shadowtls",
        listen="0.0.0.0",
        listen_port=shadowtls_listen_port,
        detour="ss-in",
        version=3,
        users=[
            NamePasswordUser(
                name="user",
                password=shadowtls_password,
            ),
        ],
        handshake=Handshake(
            server=handshake_domain,
            server_port=shadowtls_listen_port,
        ),
    )
    inbound_shadowsocks = InboundShadowsocks(
        type="shadowsocks",
        tag="ss-in",
        listen="127.0.0.1",
        method="xchacha20-ietf-poly1305",
        password=shadowtls_password,
        managed=False,
        network="tcp",
    )
    outbound_shadowsocks = OutboundShadowsocks(
        type="shadowsocks",
        tag="ss-out-exp",
        detour="shadowtls-exp",
        method="xchacha20-ietf-poly1305",
        password=shadowtls_password,
        udp_over_tcp={
            "enabled": True,
            "version": 2,
        },  # version 1.11.4 users need version 1
    )
    outbound_shadowtls = OutboundShadowTLS(
        type="shadowtls",
        tag="shadowtls-exp",
        server=server_ip,
        server_port=shadowtls_listen_port,
        version=3,
        password=shadowtls_password,
        tls=OutboundTlsCertificate(
            enabled=True,
            server_name=handshake_domain,
            insecure=False,
            certificate=[],
            utls=Utls(
                enabled=True,
                fingerprint="chrome",
            ),
        ),
    )
    inbounds_config.inbounds.append(inbound_shadowtls)
    inbounds_config.inbounds.append(inbound_shadowsocks)
    client_outbounds_config.outbounds.append(outbound_shadowtls)
    client_outbounds_config.outbounds.append(outbound_shadowsocks)
