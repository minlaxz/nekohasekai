from typing import Any, List, Literal, Dict
from dataclasses import dataclass, asdict, is_dataclass

import argparse
import logging
import json
import os
import secrets
import urllib.request


class ConfigWriter:
    def to_json(self, path: str):
        if not is_dataclass(self):
            raise TypeError("to_json expects a dataclass instance")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=4, ensure_ascii=False)


@dataclass
class DomainResolver:
    server: str
    strategy: Literal["ipv4_only", "prefer_ipv4"]


@dataclass
class OutboundDirect:
    type: Literal["direct"]
    tag: str
    domain_resolver: DomainResolver


@dataclass
class Route:
    rule_set: List[dict[str, Any]]
    rules: List[dict[str, Any]]
    final: str
    auto_detect_interface: bool


@dataclass
class RouteConfig(ConfigWriter):
    route: Route


@dataclass
class ClashAPI:
    external_controller: str
    external_ui: str
    external_ui_download_url: str
    external_ui_download_detour: str


@dataclass
class CacheFile:
    enabled: bool
    path: str


@dataclass
class Experimental:
    clash_api: ClashAPI
    cache_file: CacheFile


@dataclass
class ExperimentalConfig(ConfigWriter):
    experimental: Experimental


@dataclass
class DNSServer:
    type: str
    tag: str


@dataclass
class DNS:
    servers: List[DNSServer]


@dataclass
class DNSConfig(ConfigWriter):
    dns: DNS


@dataclass
class ShadowsocksUser:
    password: str
    method: str


@dataclass
class Brutal:
    enabled: bool
    up_mbps: int
    down_mbps: int


@dataclass
class InboundMultiplex:
    enabled: bool
    padding: bool
    brutal: Brutal


@dataclass
class OutboundMultiplex(InboundMultiplex):
    protocol: Literal["smux", "yamux", "mux"] = "smux"
    max_connections: int = 4
    min_streams: int = 4
    max_streams: int = 0


@dataclass
class ListenFields:
    listen: Literal["0.0.0.0", "::"]
    listen_port: int


@dataclass
class InboundShadowsocks(ConfigWriter, ListenFields):
    type: Literal["shadowsocks", "xtls-reality"]
    tag: str
    method: Literal["xchacha20-ietf-poly1305", "chacha20-ietf-poly1305"]
    password: str
    users: List[ShadowsocksUser]
    managed: bool
    # Listen fields ...
    # Multiplex
    multiplex: InboundMultiplex | Dict[str, Any]


@dataclass
class DailFields:
    server: str
    server_port: int
    domain_strategy: Literal["ipv4_only", "prefer_ipv4"]


@dataclass
class OutboundShadowsocks(DailFields):
    type: Literal["shadowsocks", "xtls-reality"]
    tag: Literal["shadowsocks", "xtls-reality"]
    method: Literal["xchacha20-ietf-poly1305", "chacha20-ietf-poly1305"]
    password: str
    # Dail fields ...
    # Multiplex
    multiplex: OutboundMultiplex | Dict[str, Any]


@dataclass
class SSMService:
    type: Literal["ssm-api"]
    tag: Literal["ssm-api"]
    listen: Literal["0.0.0.0", "::"]
    listen_port: int
    cache_path: str
    servers: Dict[str, str]


@dataclass
class WireguardPeer:
    public_key: str
    allowed_ips: List[str]


@dataclass
class WireguardEndpoint:
    type: str
    tag: str
    system: bool
    mtu: int
    address: List[str]
    private_key: str
    listen_port: int
    peers: List[WireguardPeer]


@dataclass
class EndpointConfig(ConfigWriter):
    endpoints: List[WireguardEndpoint]


@dataclass
class ServicesConfig(ConfigWriter):
    services: List[SSMService]


@dataclass
class InboundsConfig(ConfigWriter):
    inbounds: List[InboundShadowsocks]


@dataclass
class OutboundsConfig(ConfigWriter):
    outbounds: List[OutboundShadowsocks | OutboundDirect | SSMService]


logging.basicConfig(
    level=logging.NOTSET,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)


def main():
    resp = json.load(urllib.request.urlopen("https://myip.wtf/json"))
    server_ip = resp.get("YourFuckingIPAddress")
    domain_strategy = "ipv4_only" if "." in server_ip else "prefer_ipv4"

    parser = argparse.ArgumentParser(description="Sing-Box Config Generator Parser")
    parser.add_argument("--start-port", default=0, help="Starting port")
    parser.add_argument("--shadowsocks", action="store_true", help="Shadowsocks")
    # Not need after testing
    parser.add_argument("--wg-priv", default="", help="Private Key")
    parser.add_argument("--wg-pub", default="", help="Public Key")
    # Not need after testing
    parser.add_argument("--wg-client-priv", default="", help="Client Private Key")
    parser.add_argument("--wg-client-pub", default="", help="Client Public Key")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose")
    args = parser.parse_args()

    start_port = int(args.start_port)
    verbose = args.verbose

    is_ss_enabled = args.shadowsocks
    wg_priv = args.wg_priv
    wg_pub = args.wg_pub
    wg_client_pub = args.wg_client_pub
    wg_client_priv = args.wg_client_priv
    is_wg_enabled = all([wg_priv, wg_pub, wg_client_priv, wg_client_pub])

    ssm_listen_port = start_port + 10
    ss_listen_port = start_port + 1
    wg_listen_port = start_port + 2

    if verbose:
        logging.info(f"Start Port (Clash API): {start_port}")
        logging.info(f"End Port (SSM API): {ssm_listen_port}")
        logging.info(f"Server IP: {server_ip}")
        logging.info(f"Domain Strategy: {domain_strategy}")
        logging.info(f"Shadowsocks Enabled: {is_ss_enabled}")
        logging.info(f"WG Enabled: {is_wg_enabled}")
        logging.info(f"Server Pub Key: {wg_pub}")
        logging.info(f"Client Priv Key: {wg_client_priv}")

    logging.info("Generating Sing-Box configuration...")
    os.makedirs("conf", exist_ok=True)
    os.makedirs("public", exist_ok=True)
    os.makedirs("cache", exist_ok=True)

    outbounds_config = OutboundsConfig(
        outbounds=[
            OutboundDirect(
                type="direct",
                tag="direct-out",
                domain_resolver=DomainResolver(
                    server="local",
                    strategy=domain_strategy,
                ),
            )
        ]
    )
    outbounds_config.to_json(path="conf/01_outbounds.json")

    route_config = RouteConfig(
        route=Route(
            rule_set=[],
            rules=[],
            final="direct-out",
            auto_detect_interface=True,
        )
    )
    route_config.to_json(path="conf/02_route.json")

    external_controller_port = start_port
    experimental_config = ExperimentalConfig(
        experimental=Experimental(
            clash_api=ClashAPI(
                external_controller=f"0.0.0.0:{external_controller_port}",
                external_ui="web-ui",
                external_ui_download_url="https://github.com/MetaCubeX/metacubexd/archive/refs/heads/gh-pages.zip",
                external_ui_download_detour="direct-out",
            ),
            cache_file=CacheFile(enabled=True, path="cache/sing-box-cache.db"),
        )
    )
    experimental_config.to_json(path="conf/03_experimental.json")

    dns_config = DNSConfig(dns=DNS(servers=[DNSServer(type="local", tag="local")]))
    dns_config.to_json(path="conf/04_dns.json")

    if is_ss_enabled:
        inbounds_config = InboundsConfig(
            inbounds=[
                InboundShadowsocks(
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
            ]
        )
        inbounds_config.to_json(path="conf/05_inbounds.json")

    if is_wg_enabled:
        wg_endpoint_config = EndpointConfig(
            endpoints=[
                WireguardEndpoint(
                    type="wireguard",
                    tag="wg-ep",
                    system=False,
                    mtu=1280,
                    address=["10.10.10.0/24"],
                    private_key=wg_priv,
                    listen_port=wg_listen_port,
                    peers=[
                        WireguardPeer(
                            public_key=wg_client_pub,
                            allowed_ips=["10.10.10.2/32"],
                        )
                    ],
                )
            ]
        )
        wg_endpoint_config.to_json(path="conf/06_endpoints.json")

    services_config = ServicesConfig(
        services=[
            SSMService(
                type="ssm-api",
                tag="ssm-api",
                listen="0.0.0.0",
                listen_port=ssm_listen_port,
                cache_path="cache/ssm-cache.json",
                servers={"/": "shadowsocks"},
            )
        ]
    )
    services_config.to_json(path="conf/07_services.json")

    client_outbounds_config = OutboundsConfig(
        outbounds=[
            OutboundShadowsocks(
                type="shadowsocks",
                tag="shadowsocks",
                server=server_ip,
                server_port=ss_listen_port,
                domain_strategy=domain_strategy,
                method="xchacha20-ietf-poly1305",
                password="",
                multiplex={"enabled": False},
            ),
            SSMService(
                type="ssm-api",
                tag="ssm-api",
                listen="0.0.0.0",
                listen_port=ssm_listen_port,
                cache_path="cache/ssm-cache.json",
                servers={"/": "shadowsocks"},
            ),
        ]
    )
    client_outbounds_config.to_json(path="public/outbounds.json")
    logging.info("Sing-Box configuration generation completed.")


if __name__ == "__main__":
    logging.info("Starting Sing-Box Config Generator")
    main()
