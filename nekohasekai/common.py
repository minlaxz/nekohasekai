from typing import List
import json
import os
from dataclasses import dataclass, asdict, is_dataclass, field

from typings.log import Log
from typings.route import Route
from typings.experimental import Experimental, ClashAPI, CacheFile
from typings.dns import DNS, DNSServer
from typings.common import SSMService
from typings.shadowsocks import InboundShadowsocks, OutboundShadowsocks
from typings.trojan import InboundTrojan, OutboundTrojan
from typings.hysteria2 import InboundHysteria2, OutboundHysteria2
from typings.shadowtls import InboundShadowTLS, OutboundShadowTLS
from typings.wireguard import WireguardEndpoint
from typings.direct import ServerOutbound, DomainResolver

from constants import outbound_tag, outbound_dns_tag


class ConfigWriter:
    def to_json(self, path: str):
        if not is_dataclass(self):
            raise TypeError("to_json expects a dataclass instance")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=4, ensure_ascii=False)


@dataclass
class LogConfig(ConfigWriter):
    log: Log = field(
        default_factory=lambda: Log(
            level=os.environ.get("LOG_LEVEL", "warn").lower(),
            timestamp=True,
        )
    )


@dataclass
class RouteConfig(ConfigWriter):
    route: Route = field(
        default_factory=lambda: Route(
            rule_set=[],
            rules=[],
            final=outbound_tag,
            auto_detect_interface=True,
        )
    )


@dataclass
class ExperimentalConfig(ConfigWriter):
    experimental: Experimental = field(
        default_factory=lambda: Experimental(
            clash_api=ClashAPI(external_controller=f"0.0.0.0:{0}"),
            cache_file=CacheFile(enabled=True, path="cache/sing-box-cache.db"),
        )
    )


@dataclass
class DNSConfig(ConfigWriter):
    dns: DNS = field(
        default_factory=lambda: DNS(
            servers=[
                DNSServer(
                    type="local",
                    tag=outbound_dns_tag,
                )
            ]
        )
    )


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


@dataclass
class EndpointsConfig(ConfigWriter):
    endpoints: List[WireguardEndpoint]


@dataclass
class InboundsConfig(ConfigWriter):
    inbounds: List[
        InboundShadowsocks | InboundTrojan | InboundHysteria2 | InboundShadowTLS
    ]


@dataclass
class OutboundsConfig(ConfigWriter):
    outbounds: List[ServerOutbound] = field(
        default_factory=lambda: [
            ServerOutbound(
                type="direct",
                tag=outbound_tag,
                # Optional domain resolver
                domain_resolver=DomainResolver(
                    server=outbound_dns_tag,
                    strategy="ipv4_only",
                ),
            )
        ]
    )


@dataclass
class ClientOutboundsConfig(ConfigWriter):
    outbounds: List[
        OutboundShadowsocks | OutboundTrojan | OutboundHysteria2 | OutboundShadowTLS
    ]
