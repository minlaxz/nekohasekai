from typing import Tuple

import logging
import os
import secrets

from common import (
    ServicesConfig,
    EndpointsConfig,
    InboundsConfig,
    LogConfig,
    OutboundsConfig,
    RouteConfig,
    DNSConfig,
    ExperimentalConfig,
)
from typings.shadowsocks import InboundShadowsocks, default_inbound_ss
from typings.hysteria2 import InboundHysteria2, default_inbound_hy2
from typings.trojan import InboundTrojan, default_inbound_tj
from typings.shadowtls import InboundShadowTLS, default_inbound_stls
from constants import (
    conf_log_path,
    conf_outbounds_path,
    conf_route_path,
    conf_experimental_path,
    conf_dns_path,
    conf_inbounds_path,
    conf_services_path,
    conf_endpoints_path,
)
from utils import get_all_users_passwords

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)


class ServerConfig:
    def __init__(
        self,
        start_port: int,
        ssm_listen_port: int,
        server_ip: str,
        server_name: str,
        handshake_server_name: str = "",
        handshake_server_port: int = 443,
    ) -> None:
        self.start_port = start_port
        self.ssm_listen_port = ssm_listen_port
        self.server_ip = server_ip
        self.server_name = server_name
        self.handshake_server_name = handshake_server_name
        self.handshake_server_port = handshake_server_port
        self.users = get_all_users_passwords()

        self.services_config = ServicesConfig()
        self.endpoints_config = EndpointsConfig(endpoints=[])
        self.inbounds_config = InboundsConfig(inbounds=[])

    def _ss(self, port: int) -> InboundShadowsocks:
        return default_inbound_ss(port=port)

    def _hy2(self, port: int, obfs_password: str) -> InboundHysteria2:
        return default_inbound_hy2(
            server_name=self.server_name,
            listen_port=port,
            obfs_password=obfs_password,
            users=self.users,
        )

    def _tj(self, port: int) -> InboundTrojan:
        return default_inbound_tj(
            server_name=self.server_name,
            listen_port=port,
            users=self.users,
        )

    def _stls(
        self, port: int, ss_password: str
    ) -> Tuple[InboundShadowsocks, InboundShadowTLS]:
        return default_inbound_stls(
            listen_port=port,
            users=self.users,
            handshake_domain=self.handshake_server_name,
            handshake_port=self.handshake_server_port,
            ss_password=ss_password,
        )

    def add(self, proxy_name: str, port: int) -> None:
        if proxy_name == "shadowsocks":
            logging.info(f"Adding Shadowsocks inbound on port {port}...")
            self.inbounds_config.inbounds.append(self._ss(port=port))
            self.services_config.services[0]["listen_port"] = self.ssm_listen_port
            self.services_config.services[0]["servers"] = {"/": "shadowsocks"}
        elif proxy_name == "hysteria2":
            obfs_password = os.getenv("HYSTERIA2_OBFS_PASSWORD", "")
            logging.info("Using existing Hysteria2 obfs password.")
            if not obfs_password:
                logging.info("Generating new Hysteria2 obfs password...")
                obfs_password = secrets.token_urlsafe(16)
            os.environ["HYSTERIA2_OBFS_PASSWORD"] = obfs_password
            logging.info(f"Adding Hysteria2 outbound {self.server_ip}:{port}...")
            self.inbounds_config.inbounds.append(
                self._hy2(port=port, obfs_password=obfs_password)
            )
        elif proxy_name == "trojan":
            logging.info(f"Adding Trojan inbound on port {port}...")
            self.inbounds_config.inbounds.append(self._tj(port=port))
        elif proxy_name == "shadowtls":
            ss_password = os.getenv("SHADOWTLS_SS_PASSWORD", "")
            logging.info("Using existing ShadowTLS Shadowsocks password.")
            if not ss_password:
                logging.info("Generating new ShadowTLS Shadowsocks password...")
                ss_password = secrets.token_urlsafe(16)
            os.environ["SHADOWTLS_SS_PASSWORD"] = ss_password
            self.inbounds_config.inbounds.extend(
                self._stls(port=port, ss_password=ss_password)
            )
            logging.info(f"Adding ShadowTLS inbound on port {port}...")
        else:
            logging.warning(f"Unknown proxy {proxy_name}, skipping...")

    def write(self) -> None:
        LogConfig().to_json(path=conf_log_path)
        OutboundsConfig().to_json(path=conf_outbounds_path)
        RouteConfig().to_json(path=conf_route_path)
        DNSConfig().to_json(path=conf_dns_path)
        clash_endpoint = f"0.0.0.0:{self.start_port}"
        exp_config = ExperimentalConfig()
        exp_config.experimental["clash_api"]["external_controller"] = clash_endpoint
        exp_config.to_json(path=conf_experimental_path)
        self.services_config.to_json(path=conf_services_path)
        self.endpoints_config.to_json(path=conf_endpoints_path)
        self.inbounds_config.to_json(path=conf_inbounds_path)
