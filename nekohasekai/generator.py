from typing import Any, List, Literal, Dict, Optional, TypedDict
from dataclasses import dataclass, asdict, is_dataclass, field


import argparse
import base64
import logging
import json
import os
import secrets
import urllib.request

from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives import serialization


class ConfigWriter:
    def to_json(self, path: str):
        if not is_dataclass(self):
            raise TypeError("to_json expects a dataclass instance")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=4, ensure_ascii=False)


class Log(TypedDict):
    level: Literal["trce", "debug", "info", "warn", "error"]
    timestamp: bool


@dataclass
class LogConfig(ConfigWriter):
    log: Log = field(default_factory=lambda: Log(level="info", timestamp=True))


# --- Log Config End ---


class Route(TypedDict):
    rule_set: List[dict[str, Any]]
    rules: List[dict[str, Any]]
    final: str
    auto_detect_interface: bool


@dataclass
class RouteConfig(ConfigWriter):
    route: Route = field(
        default_factory=lambda: Route(
            rule_set=[],
            rules=[],
            final="direct-out",
            auto_detect_interface=True,
        )
    )


# --- Route Config End ---


class ClashAPI(TypedDict):
    external_controller: str
    external_ui: str
    external_ui_download_url: str
    external_ui_download_detour: str


class CacheFile(TypedDict):
    enabled: bool
    path: str


class Experimental(TypedDict):
    clash_api: ClashAPI
    cache_file: CacheFile


@dataclass
class ExperimentalConfig(ConfigWriter):
    experimental: Experimental = field(
        default_factory=lambda: Experimental(
            clash_api=ClashAPI(
                external_controller=f"0.0.0.0:{0}",
                external_ui="web-ui",
                external_ui_download_url="https://github.com/MetaCubeX/metacubexd/archive/refs/heads/gh-pages.zip",
                external_ui_download_detour="direct-out",
            ),
            cache_file=CacheFile(enabled=True, path="cache/sing-box-cache.db"),
        )
    )


# -- Experimental Config End ---


class DNSServer(TypedDict):
    type: str
    tag: str


class DNS(TypedDict):
    servers: List[DNSServer]


@dataclass
class DNSConfig(ConfigWriter):
    dns: DNS = field(
        default_factory=lambda: DNS(servers=[DNSServer(type="local", tag="local")])
    )


# --- DNS Config End ---


class Brutal(TypedDict):
    enabled: bool
    up_mbps: Optional[int]
    down_mbps: Optional[int]


class Multiplex(TypedDict):
    enabled: bool
    padding: bool
    brutal: Brutal


class InboundMultiplex(Multiplex):
    pass


class OutboundMultiplex(Multiplex):
    protocol: Literal["smux", "yamux", "h2mux"]
    max_connections: int
    min_streams: int
    max_streams: int


# --- Multiplex Config End ---


class CommonFields(TypedDict):
    tag: str
    type: Literal["shadowsocks", "vless", "ssm-api", "wireguard", "trojan", "hysteria2"]


class ListenFields(TypedDict):
    listen: Literal["0.0.0.0", "::"]
    listen_port: int


class Handshake(TypedDict):
    server: str
    server_port: int


class ServerReality(TypedDict):
    enabled: bool
    private_key: str
    short_id: List[str | None]
    handshake: Handshake


class Tls(TypedDict):
    enabled: bool
    server_name: str
    alpn: Optional[List[str]]
    min_version: Literal["1.3", "1.2", "1.1", "1.0"]
    max_version: Literal["1.3", "1.2", "1.1", "1.0"]


class ServerRealityTLS(Tls):
    reality: ServerReality


class ServerCertificateTLS(Tls):
    key_path: str
    certificate_path: str


class Utls(TypedDict):
    enabled: bool
    fingerprint: Literal["chrome", "firefox", "safari", "edge"]


class ClientReality(TypedDict):
    enabled: bool
    public_key: str
    short_id: str


class ClientTLSReality(Tls):
    utls: Utls
    reality: ClientReality


class ClientTLSInsecure(Tls):
    utls: Optional[Utls]
    insecure: bool


class Shadowsocks(TypedDict):
    method: Literal["xchacha20-ietf-poly1305", "chacha20-ietf-poly1305"]
    password: str


class ShadowsocksUser(TypedDict):
    password: str
    method: str


class NamePasswordUser(TypedDict):
    name: str
    password: str


class InboundShadowsocks(CommonFields, ListenFields, Shadowsocks):
    users: List[ShadowsocksUser]
    managed: bool
    multiplex: InboundMultiplex | Dict[str, Any]


class InboundTrojan(CommonFields, ListenFields):
    users: List[NamePasswordUser]
    tls: ServerCertificateTLS | ServerRealityTLS
    multiplex: InboundMultiplex | Dict[str, Any]


class Obfs(TypedDict):
    type: Literal["salamander"]
    password: str


class MasqueradeConfig(TypedDict):
    type: Literal["file", "proxy", "string"]
    directory: Optional[str] # if type is file
    url: Optional[str] # if type is proxy
    rewrite_host: Optional[str]
    status_code: Optional[int] # if type is string
    headers: Optional[Dict[str, str]]
    content: Optional[str]


class InboundHysteria2(CommonFields, ListenFields):
    up_mbps: int
    down_mbps: int
    obfs: Obfs
    users: List[NamePasswordUser]
    ignore_client_bandwidth: bool
    tls: ServerCertificateTLS | ServerRealityTLS
    masquerade: MasqueradeConfig | Dict[str, Any]
    brutal_debug: bool


class DailFields(TypedDict):
    server: str
    server_port: int
    domain_strategy: Literal["ipv4_only", "prefer_ipv4", "ipv6_only", "ipv6_prefer"]


class OutboundShadowsocks(CommonFields, DailFields, Shadowsocks):
    multiplex: OutboundMultiplex | Dict[str, Any]


class OutboundTrojan(CommonFields, DailFields):
    password: str
    tls: ClientTLSInsecure
    multiplex: OutboundMultiplex | Dict[str, Any]


class OutboundHysteria2(CommonFields, DailFields):
    up_mbps: int
    down_mbps: int
    obfs: Obfs
    password: str
    tls: ClientTLSInsecure
    brutal_debug: bool


# --- Shadowsocks Config End ---


class SSMService(CommonFields, ListenFields):
    cache_path: str
    servers: Dict[str, str]


@dataclass
class ServicesConfig(ConfigWriter):
    services: List[SSMService] = field(
        default_factory=lambda: [
            SSMService(
                type="ssm-api",
                tag="ssm-api",
                listen="0.0.0.0",
                listen_port=0,
                cache_path="cache/ssm-cache.json",
                servers={"/": "shadowsocks"},
            )
        ]
    )


# --- Services Config End ---


class WireguardPeer(TypedDict):
    public_key: str
    allowed_ips: List[str]


class WireguardEndpoint(CommonFields):
    name: str
    system: bool
    mtu: int
    address: List[str]
    private_key: str
    listen_port: int
    peers: List[WireguardPeer]


@dataclass
class EndpointsConfig(ConfigWriter):
    endpoints: List[WireguardEndpoint]


# --- Endpoint Config End ---


@dataclass
class InboundsConfig(ConfigWriter):
    inbounds: List[InboundShadowsocks | InboundTrojan | InboundHysteria2]


class WireguardKeys(TypedDict):
    tag: str
    keys: Dict[str, str]  # = field(default_factory=dict[str, str])


class DomainResolver(TypedDict):
    server: str
    strategy: Literal["ipv4_only", "prefer_ipv4"]


class ServerOutbound(TypedDict):
    type: Literal["direct", "shadowsocks", "socks"]
    tag: str
    domain_resolver: DomainResolver


@dataclass
class ServerOutboundsConfig(ConfigWriter):
    outbounds: List[ServerOutbound] = field(
        default_factory=lambda: [
            ServerOutbound(
                type="direct",
                tag="direct-out",
                domain_resolver=DomainResolver(
                    server="local",
                    strategy="ipv4_only",
                ),
            )
        ]
    )


@dataclass
class ClientOutboundsConfig(ConfigWriter):
    outbounds: List[OutboundShadowsocks | OutboundTrojan | OutboundHysteria2]


logging.basicConfig(
    level=logging.NOTSET,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)


def keys() -> Dict[str, str]:
    private_key = x25519.X25519PrivateKey.generate()
    private_key_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_key = private_key.public_key()
    public_key_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    private_key_b64 = base64.b64encode(private_key_bytes).decode()
    public_key_b64 = base64.b64encode(public_key_bytes).decode()
    return {
        "private": private_key_b64,
        "public": public_key_b64,
    }


def main() -> None:
    resp = json.load(urllib.request.urlopen("https://myip.wtf/json"))
    server_ip = resp.get("YourFuckingIPAddress")
    domain_strategy = "ipv4_only" if "." in server_ip else "prefer_ipv4"

    parser = argparse.ArgumentParser(description="Sing-Box Config Generator Parser")
    parser.add_argument("--start-port", default=0, help="Starting port")
    parser.add_argument("--end-port", default=0, help="Ending port")
    parser.add_argument("--log-level", default="info", help="Log Level")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose")
    args = parser.parse_args()

    start_port = int(args.start_port)
    ssm_listen_port = int(args.end_port) or start_port + 10
    verbose = args.verbose

    is_ss_enabled = os.environ.get("SHADOWSOCKS", "false").lower() == "true"
    is_trojan_enabled = os.environ.get("TROJAN", "false").lower() == "true"
    is_hysteria2_enabled = os.environ.get("HYSTERIA2", "false").lower() == "true"

    handshake_domain = os.environ.get("HANDSHAKE_DOMAIN", "")
    # reality_privatekey = os.environ.get("REALITY_PRIVATEKEY", "")
    # reality_publickey = os.environ.get("REALITY_PUBLICKEY", "")

    if verbose:
        logging.info(f"Start Port (Clash API): {start_port}")
        logging.info(f"End Port (SSM API): {ssm_listen_port}")
        logging.info(f"Server IP: {server_ip}")
        logging.info(f"Domain Strategy: {domain_strategy}")
        logging.info(f"Shadowsocks Enabled: {is_ss_enabled}")
        logging.info(f"Trojan Enabled: {is_trojan_enabled}")
        logging.info(f"Hysteria2 Enabled: {is_hysteria2_enabled}")

    logging.info("Generating Sing-Box configuration...")
    os.makedirs("conf", exist_ok=True)
    os.makedirs("public", exist_ok=True)
    os.makedirs("cache", exist_ok=True)

    log_config = LogConfig()
    log_config.log["level"] = args.log_level
    log_config.to_json(path="conf/00_log.json")

    ServerOutboundsConfig().to_json(path="conf/01_outbounds.json")

    RouteConfig().to_json(path="conf/02_route.json")
    exp_config = ExperimentalConfig()
    exp_config.experimental["clash_api"]["external_controller"] = (
        f"0.0.0.0:{start_port}"
    )
    exp_config.to_json(path="conf/03_experimental.json")

    DNSConfig().to_json(path="conf/04_dns.json")

    inbounds_config = InboundsConfig(inbounds=[])
    services_config = ServicesConfig()
    endpoints_config = EndpointsConfig(endpoints=[])
    client_outbounds_config = ClientOutboundsConfig(outbounds=[])

    curr = start_port

    if is_ss_enabled:
        ss_listen_port = curr = curr + 1
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
            domain_strategy=domain_strategy,
            method="xchacha20-ietf-poly1305",
            password="",
            multiplex=OutboundMultiplex(
                protocol="h2mux",
                enabled=True,
                padding=False,
                max_connections=4,
                min_streams=16,
                max_streams=256,
                # Brual is too flat
                brutal=Brutal(enabled=False, up_mbps=0, down_mbps=0),
            ),
        )
        inbounds_config.inbounds.append(inbound_shadowsocks)
        client_outbounds_config.outbounds.append(outbound_shadowsocks)
        services_config.services[0]["listen_port"] = ssm_listen_port
        services_config.services[0]["servers"] = {"/": inbound_shadowsocks["tag"]}

    if is_trojan_enabled:
        trojan_listen_port = curr = curr + 1
        trojan_password = secrets.token_urlsafe(12) + "=="
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
            tls=ServerCertificateTLS(
                enabled=True,
                server_name=handshake_domain,
                alpn=["h2", "http/1.1"],
                min_version="1.2",
                max_version="1.3",
                key_path="certs/private.key",
                certificate_path="certs/cert.pem",
            ),
            multiplex=InboundMultiplex(
                enabled=True,
                padding=False,
                brutal=Brutal(enabled=False, up_mbps=None, down_mbps=None),
            ),
        )
        outbound_trojan = OutboundTrojan(
            type="trojan",
            tag="trojan",
            server=server_ip,
            server_port=trojan_listen_port,
            domain_strategy=domain_strategy,
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
                max_connections=4,
                min_streams=16,
                max_streams=256,
                brutal=Brutal(enabled=False, up_mbps=None, down_mbps=None),
            ),
        )
        inbounds_config.inbounds.append(inbound_trojan)
        client_outbounds_config.outbounds.append(outbound_trojan)

    if is_hysteria2_enabled:
        hysteria2_listen_port = curr = curr + 1
        hysteria2_obfs_password = secrets.token_urlsafe(22)
        hysteria2_password = secrets.token_urlsafe(22) + "=="
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
            tls=ServerCertificateTLS(
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
            domain_strategy=domain_strategy,
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

    inbounds_config.to_json(path="conf/05_inbounds.json")
    services_config.to_json(path="conf/06_services.json")
    endpoints_config.to_json(path="conf/07_endpoints.json")
    client_outbounds_config.to_json(path="public/outbounds.json")

    logging.info("Sing-Box configuration generation completed.")


if __name__ == "__main__":
    logging.info("Starting Sing-Box Config Generator")
    main()
