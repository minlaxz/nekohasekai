from typings.shadowsocks import InboundShadowsocks
from typings.shadowsocks import OutboundShadowsocks
from typings.multiplex import InboundMultiplex, OutboundMultiplex, Brutal
from common import InboundsConfig, ClientOutboundsConfig, ServicesConfig


def generate(
    ss_listen_port: int,
    ssm_listen_port: int,
    server_ip: str,
    inbounds_config: InboundsConfig,
    client_outbounds_config: ClientOutboundsConfig,
    services_config: ServicesConfig,
):
    inbound_shadowsocks = InboundShadowsocks(
        type="shadowsocks",
        tag="shadowsocks",
        listen="0.0.0.0",
        listen_port=ss_listen_port,
        method="xchacha20-ietf-poly1305",
        password="",
        users=[],
        managed=True,
        multiplex=InboundMultiplex(
            enabled=True,
            padding=False,
            # Brual is too flat
            brutal=Brutal(enabled=False, up_mbps=0, down_mbps=0),
        ),
    )
    outbound_shadowsocks = OutboundShadowsocks(
        type="shadowsocks",
        tag="shadowsocks",
        server=server_ip,
        server_port=ss_listen_port,
        method="xchacha20-ietf-poly1305",
        password="",
        multiplex=OutboundMultiplex(
            protocol="h2mux",
            enabled=True,
            padding=False,
            max_connections=1,
            min_streams=4,
            max_streams=8,
            # Brual is too flat
            brutal=Brutal(enabled=False, up_mbps=0, down_mbps=0),
        ),
    )
    inbounds_config.inbounds.append(inbound_shadowsocks)
    client_outbounds_config.outbounds.append(outbound_shadowsocks)
    services_config.services[0]["listen_port"] = ssm_listen_port
    services_config.services[0]["servers"] = {"/": inbound_shadowsocks["tag"]}