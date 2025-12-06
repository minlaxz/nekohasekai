from typing import Any, List, Literal, Dict, TypedDict
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
    up_mbps: int
    down_mbps: int


class Multiplex(TypedDict):
    enabled: bool
    padding: bool
    brutal: Brutal


class InboundMultiplex(Multiplex):
    pass


class OutboundMultiplex(Multiplex):
    protocol: Literal["smux", "yamux", "mux"]
    max_connections: int
    min_streams: int
    max_streams: int


# --- Multiplex Config End ---


class CommonFields(TypedDict):
    tag: str
    type: Literal["shadowsocks", "vless", "ssm-api", "wireguard", "trojan"]


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
    utls: Utls
    insecure: bool


class Shadowsocks(TypedDict):
    method: Literal["xchacha20-ietf-poly1305", "chacha20-ietf-poly1305"]
    password: str


class ShadowsocksUser(TypedDict):
    password: str
    method: str


class TrojanUser(TypedDict):
    name: str
    password: str


class InboundShadowsocks(CommonFields, ListenFields, Shadowsocks):
    users: List[ShadowsocksUser]
    managed: bool
    multiplex: InboundMultiplex | Dict[str, Any]


class InboundTrojan(CommonFields, ListenFields):
    users: List[TrojanUser]
    tls: ServerCertificateTLS | ServerRealityTLS
    multiplex: InboundMultiplex | Dict[str, Any]


class DailFields(TypedDict):
    server: str
    server_port: int
    domain_strategy: Literal["ipv4_only", "prefer_ipv4"]


class OutboundShadowsocks(CommonFields, DailFields, Shadowsocks):
    multiplex: OutboundMultiplex | Dict[str, Any]


class OutboundTrojan(CommonFields, DailFields):
    password: str
    tls: ClientTLSInsecure


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
class EndpointConfig(ConfigWriter):
    endpoints: List[WireguardEndpoint]


# --- Endpoint Config End ---


@dataclass
class InboundsConfig(ConfigWriter):
    inbounds: List[InboundShadowsocks | InboundTrojan]


class WireguardKeys(TypedDict):
    tag: str
    keys: Dict[str, str]  # = field(default_factory=dict[str, str])


class DomainResolver(TypedDict):
    server: str
    strategy: Literal["ipv4_only", "prefer_ipv4"]


class OutboundDirect(TypedDict):
    type: Literal["direct"]
    tag: str
    domain_resolver: DomainResolver


@dataclass
class ServerOutboundsConfig(ConfigWriter):
    outbounds: List[OutboundDirect] = field(
        default_factory=lambda: [
            OutboundDirect(
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
    outbounds: List[OutboundShadowsocks | OutboundTrojan | SSMService | WireguardKeys]


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

    parser.add_argument("--shadowsocks", action="store_true", help="Shadowsocks")

    parser.add_argument("--trojan", action="store_true", help="Trojan")
    parser.add_argument("--handshake-domain", default="", help="Handshake Domain")
    parser.add_argument("--reality-privatekey", default="", help="Reality Private Key")
    parser.add_argument("--reality-publickey", default="", help="Reality Public Key")

    parser.add_argument("--wg-pc", default=0, help="Wireguard Peer Count")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose")
    parser.add_argument("--log-level", default="info", help="Log Level")
    args = parser.parse_args()

    start_port = int(args.start_port)
    end_port = int(args.end_port)
    ssm_listen_port = end_port or start_port + 10
    verbose = args.verbose

    is_ss_enabled = args.shadowsocks
    is_trojan_enabled = all([
        args.trojan,
        args.handshake_domain,
    ])
    trojan_password = secrets.token_urlsafe(12) + "=="
    wg_pc = int(args.wg_pc)
    is_wg_enabled = 0 < wg_pc < 254
    ss_listen_port = start_port + 1
    trojan_listen_port = start_port + 2
    wg_listen_port = start_port + 3

    if verbose:
        logging.info(f"Start Port (Clash API): {start_port}")
        logging.info(f"End Port (SSM API): {ssm_listen_port}")
        logging.info(f"Server IP: {server_ip}")
        logging.info(f"Domain Strategy: {domain_strategy}")
        logging.info(f"Shadowsocks Enabled: {is_ss_enabled}")
        logging.info(f"Trojan Enabled: {is_trojan_enabled}")
        logging.info(f"WG Enabled: {is_wg_enabled}")

    logging.info("Generating Sing-Box configuration...")
    os.makedirs("conf", exist_ok=True)
    os.makedirs("public", exist_ok=True)
    os.makedirs("cache", exist_ok=True)

    LogConfig().to_json(path="conf/00_log.json")

    ServerOutboundsConfig().to_json(path="conf/01_outbounds.json")

    RouteConfig().to_json(path="conf/02_route.json")
    exp_config = ExperimentalConfig()
    exp_config.experimental["clash_api"]["external_controller"] = (
        f"0.0.0.0:{start_port}"
    )
    exp_config.to_json(path="conf/03_experimental.json")

    DNSConfig().to_json(path="conf/04_dns.json")

    inbound_config = InboundsConfig(inbounds=[])
    if is_ss_enabled:
        inbound_shadowsocks = InboundShadowsocks(
            type="shadowsocks",
            tag="shadowsocks",
            listen="0.0.0.0",
            listen_port=ss_listen_port,
            method="xchacha20-ietf-poly1305",
            password=secrets.token_urlsafe(12) + "==",
            users=[],
            managed=True,
            multiplex=InboundMultiplex(
                enabled=True,
                padding=False,
                brutal=Brutal(enabled=True, up_mbps=10, down_mbps=50),
            ),
        )
        inbound_config.inbounds.append(inbound_shadowsocks)
        services_config = ServicesConfig()
        services_config.services[0]["listen_port"] = ssm_listen_port
        services_config.services[0]["servers"] = {"/": inbound_shadowsocks["tag"]}
        services_config.to_json(path="conf/06_services.json")

    if is_trojan_enabled:
        inbound_trojan = InboundTrojan(
            type="trojan",
            tag="trojan",
            listen="0.0.0.0",
            listen_port=trojan_listen_port,
            users=[
                TrojanUser(
                    name="user",
                    password=trojan_password,
                ),
            ],
            tls=ServerCertificateTLS(
                enabled=True,
                server_name=args.handshake_domain,
                key_path="certs/private.key",
                certificate_path="certs/cert.pem",
            ),
            multiplex=InboundMultiplex(
                enabled=True,
                padding=False,
                brutal=Brutal(enabled=True, up_mbps=10, down_mbps=50),
            ),
        )
        inbound_config.inbounds.append(inbound_trojan)
    inbound_config.to_json(path="conf/05_inbounds.json")

    keys_dict: Dict[str, Any] = {}
    if is_wg_enabled:
        # Interface
        wg_keys = keys()
        keys_dict["wg_priv_0"] = wg_keys["private"]
        keys_dict["wg_pub_0"] = wg_keys["public"]
        keys_dict["wg_address_0"] = "10.10.10.1/24"

        # peers start from 1 to wg peer count
        # for example, wg_pc = 3 => peers: wg1, wg2, wg3
        for i in range(1, wg_pc + 1):
            wg_keys = keys()
            keys_dict[f"wg_priv_{i}"] = wg_keys["private"]
            keys_dict[f"wg_pub_{i}"] = wg_keys["public"]
            # 10.10.10.2 is static ip for server, look at docker-compose.yml wg subnet
            # .0 is network address, identify the subnet itself not a host
            # .255 is broadcast address (for a /24 subnet)
            keys_dict[f"wg_address_{i}"] = f"10.10.10.{i + 1}/32"

        peers: List[WireguardPeer] = [
            WireguardPeer(
                public_key=keys_dict.get(f"wg_pub_{i}", ""),
                allowed_ips=keys_dict.get(f"wg_address_{i}", ""),
            )
            for i in range(1, wg_pc + 1)
        ]

        wg_endpoint_config = EndpointConfig(
            endpoints=[
                WireguardEndpoint(
                    type="wireguard",
                    tag="wg-ep",
                    name="wg0",
                    system=False,
                    mtu=1280,
                    address=[keys_dict["wg_address_0"]],
                    private_key=keys_dict["wg_priv_0"],
                    listen_port=wg_listen_port,
                    peers=peers,
                )
            ]
        )
        wg_endpoint_config.to_json(path="conf/07_endpoints.json")

    client_outbounds_config = ClientOutboundsConfig(outbounds=[])
    if is_ss_enabled:
        client_outbounds_config.outbounds.append(
            OutboundShadowsocks(
                type="shadowsocks",
                tag="shadowsocks",
                server=server_ip,
                server_port=ss_listen_port,
                domain_strategy=domain_strategy,
                method="xchacha20-ietf-poly1305",
                password="",
                multiplex={"enabled": False},
            )
        )
        client_outbounds_config.outbounds.append(
            SSMService(
                type="ssm-api",
                tag="ssm-api",
                listen="0.0.0.0",
                listen_port=ssm_listen_port,
                cache_path="cache/ssm-cache.json",
                servers={"/": "shadowsocks"},
            )
        )
    if is_trojan_enabled:
        client_outbounds_config.outbounds.append(
            OutboundTrojan(
                type="trojan",
                tag="trojan",
                server=server_ip,
                server_port=trojan_listen_port,
                domain_strategy=domain_strategy,
                password=trojan_password,
                tls=ClientTLSInsecure(
                    enabled=True,
                    server_name=args.handshake_domain,
                    utls=Utls(
                        enabled=True,
                        fingerprint="chrome",
                    ),
                    insecure=True,
                ),
            )
        )
    if is_wg_enabled:
        client_outbounds_config.outbounds.append(
            WireguardKeys(tag="wg-keys", keys=keys_dict)
        )

    client_outbounds_config.to_json(path="public/outbounds.json")
    logging.info("Sing-Box configuration generation completed.")


if __name__ == "__main__":
    logging.info("Starting Sing-Box Config Generator")
    main()
