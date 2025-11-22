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
class Outbound:
    type: str
    tag: str
    domain_resolver: DomainResolver


@dataclass
class OutboundsConfig(ConfigWriter):
    outbounds: List[Outbound]


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
    up_mps: int
    down_mps: int


@dataclass
class Multiplex:
    enabled: bool
    padding: bool
    brutal: Brutal


@dataclass
class ShadowsocksInbound:
    type: Literal["shadowsocks", "xtls-reality"]
    tag: str
    listen: Literal["0.0.0.0", "::"]
    listen_port: int
    method: Literal["xchacha20-ietf-poly1305", "chacha20-ietf-poly1305"]
    password: str
    users: List[ShadowsocksUser]
    managed: bool
    multiplex: Multiplex | None = None


@dataclass
class InboundsConfig(ConfigWriter):
    inbounds: List[ShadowsocksInbound]


@dataclass
class ShadowsocksClientOutbound(ConfigWriter):
    type: Literal["shadowsocks"]
    tag: Literal["shadowsocks"]
    server: str
    server_port: int
    domain_strategy: Literal["ipv4_only", "prefer_ipv4"]
    method: Literal["xchacha20-ietf-poly1305", "chacha20-ietf-poly1305"]
    password: str
    multiplex: Multiplex | Dict[str, Any]


@dataclass
class SSM:
    type: Literal["ssm-api"]
    tag: Literal["ssm-api"]
    listen: Literal["0.0.0.0", "::"]
    listen_port: int
    cache_path: str
    servers: Dict[str, str]


@dataclass
class ClientOutboundsConfig(ConfigWriter):
    oudbounds: List[ShadowsocksClientOutbound | SSM]


@dataclass
class ServicesConfig(ConfigWriter):
    services: List[SSM]


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
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose")
    args = parser.parse_args()

    start_port = int(args.start_port)
    end_port = start_port + 10
    shadowsocks = args.shadowsocks
    verbose = args.verbose

    if verbose:
        logging.info(f"Start Port (Clash API): {start_port}")
        logging.info(f"End Port (SSM API): {end_port}")
        logging.info(f"Server IP: {server_ip}")
        logging.info(f"Domain Strategy: {domain_strategy}")
        logging.info(f"Shadowsocks Enabled: {shadowsocks}")

    logging.info("Generating Sing-Box configuration...")
    os.makedirs("conf", exist_ok=True)
    os.makedirs("public", exist_ok=True)

    outbounds_config = OutboundsConfig(
        outbounds=[
            Outbound(
                type="direct",
                tag="direct-out",
                domain_resolver=DomainResolver(
                    server="local", strategy=domain_strategy
                ),
            )
        ]
    )
    outbounds_config.to_json(path="conf/01_outbounds.json")

    route_config = RouteConfig(
        route=Route(
            rule_set=[], rules=[], final="direct-out", auto_detect_interface=True
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

    shadowsocks_listen_port = start_port + 1
    inbounds_config = InboundsConfig(
        inbounds=[
            ShadowsocksInbound(
                type="shadowsocks",
                tag="shadowsocks",
                listen="0.0.0.0",
                listen_port=shadowsocks_listen_port,
                method="xchacha20-ietf-poly1305",
                password=secrets.token_urlsafe(12) + "==",
                users=[],
                managed=True,
                multiplex=Multiplex(
                    enabled=True,
                    padding=False,
                    brutal=Brutal(enabled=True, up_mps=10, down_mps=50),
                ),
            )
        ]
        if shadowsocks
        else []
    )
    inbounds_config.to_json(path="conf/05_inbounds.json")

    ssm_listen_port = end_port
    services_config = ServicesConfig(
        services=[
            SSM(
                type="ssm-api",
                tag="ssm-api",
                listen="0.0.0.0",
                listen_port=ssm_listen_port,
                cache_path="cache/ssm-cache.db",
                servers={"/": "shadowsocks"},
            )
        ]
    )
    services_config.to_json(path="conf/06_services.json")

    client_outbounds_config = ClientOutboundsConfig([
        ShadowsocksClientOutbound(
            type="shadowsocks",
            tag="shadowsocks",
            server=server_ip,
            server_port=shadowsocks_listen_port,
            domain_strategy=domain_strategy,
            method="xchacha20-ietf-poly1305",
            password="",
            multiplex={"enabled": False},
        ),
        SSM(
            type="ssm-api",
            tag="ssm-api",
            listen="0.0.0.0",
            listen_port=ssm_listen_port,
            cache_path="cache/ssm-cache.db",
            servers={"/": "shadowsocks"},
        ),
    ])
    client_outbounds_config.to_json(path="public/outbounds.json")
    logging.info("Sing-Box configuration generation completed.")


if __name__ == "__main__":
    logging.info("Starting Sing-Box Config Generator")
    main()
