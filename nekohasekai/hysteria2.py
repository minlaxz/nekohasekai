from typings.hysteria2 import InboundHysteria2
from typings.hysteria2 import OutboundHysteria2
from typings.hysteria2 import Obfs
from typings.common import NamePasswordUser
from typings.tls import InboundTLSCertificate
from typings.tls import ClientTLSInsecure
from common import InboundsConfig, ClientOutboundsConfig


def generate(
    hysteria2_listen_port: int,
    hysteria2_obfs_password: str,
    hysteria2_password: str,
    handshake_domain: str,
    server_ip: str,
    inbounds_config: InboundsConfig,
    client_outbounds_config: ClientOutboundsConfig,
):
    pass

    inbound_hysteria2 = InboundHysteria2(
        type="hysteria2",
        tag="hysteria2",
        listen="0.0.0.0",
        listen_port=hysteria2_listen_port,
        up_mbps=100,
        down_mbps=100,
        obfs=Obfs(
            type="salamander",
            password=hysteria2_obfs_password,
        ),
        users=[
            NamePasswordUser(
                name="user",
                password=hysteria2_password,
            ),
        ],
        ignore_client_bandwidth=True,
        tls=InboundTLSCertificate(
            enabled=True,
            server_name=handshake_domain,
            alpn=["h3", "h2", "http/1.1"],
            min_version="1.2",
            max_version="1.3",
            key_path="certs/private.key",
            certificate_path="certs/cert.pem",
        ),
        masquerade={},
        brutal_debug=False,
    )
    outbound_hysteria2 = OutboundHysteria2(
        type="hysteria2",
        tag="hysteria2",
        server=server_ip,
        server_port=hysteria2_listen_port,
        up_mbps=100,
        down_mbps=100,
        obfs=Obfs(
            type="salamander",
            password=hysteria2_obfs_password,
        ),
        password=hysteria2_password,
        tls=ClientTLSInsecure(
            enabled=True,
            server_name=f"{handshake_domain}:{hysteria2_listen_port}",
            alpn=["h3", "h2", "http/1.1"],
            min_version="1.2",
            max_version="1.3",
            insecure=True,
            utls=None,
        ),
        brutal_debug=False,
    )
    client_outbounds_config.outbounds.append(outbound_hysteria2)
    inbounds_config.inbounds.append(inbound_hysteria2)
