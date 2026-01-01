from typing import Tuple

import logging
import os
import secrets

from common import ClientOutboundsConfig
from typings.hysteria2 import OutboundHysteria2, default_outbound_hy2
from typings.trojan import OutboundTrojan, default_outbound_tj
from typings.shadowsocks import OutboundShadowsocks, default_outbound_ss
from typings.shadowtls import OutboundShadowTLS, default_outbound_stls
from constants import public_outbounds_path

logging.basicConfig(
    level=logging.NOTSET,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)


class ClientConfig:
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

        self.outbounds_config = ClientOutboundsConfig(outbounds=[])

    def _ss(self, port: int) -> OutboundShadowsocks:
        return default_outbound_ss(
            server_ip=self.server_ip,
            port=port,
        )

    def _hy2(self, port: int, obfs_password: str) -> OutboundHysteria2:
        return default_outbound_hy2(
            server_name=self.server_name,
            server_port=port,
            obfs_password=obfs_password,
        )

    def _tj(self, port: int) -> OutboundTrojan:
        return default_outbound_tj(
            server_name=self.server_name,
            server_port=port,
        )

    def _stls(self, port: int, ss_password: str) -> Tuple[OutboundShadowTLS, OutboundShadowsocks]:
        return default_outbound_stls(
            server_ip=self.server_ip,
            server_port=port,
            ss_password=ss_password,
        )

    def add(self, proxy_name: str, port: int) -> None:
        if proxy_name == "shadowsocks":
            logging.info(f"Adding Shadowsocks outbound {self.server_ip}:{port}...")
            self.outbounds_config.outbounds.append(self._ss(port=port))
        elif proxy_name == "hysteria2":
            obfs_password = os.getenv("HYSTERIA2_OBFS_PASSWORD", "")
            logging.info("Using existing Hysteria2 obfs password.")
            if not obfs_password:
                logging.info("Generating new Hysteria2 obfs password...")
                obfs_password = secrets.token_urlsafe(16)
            os.environ["HYSTERIA2_OBFS_PASSWORD"] = obfs_password
            logging.info(f"Adding Hysteria2 outbound {self.server_ip}:{port}...")
            self.outbounds_config.outbounds.append(
                self._hy2(port=port, obfs_password=obfs_password)
            )
        elif proxy_name == "trojan":
            logging.info(f"Adding Trojan outbound {self.server_ip}:{port}...")
            self.outbounds_config.outbounds.append(self._tj(port=port))
        elif proxy_name == "shadowtls":
            ss_password = os.getenv("SHADOWTLS_SS_PASSWORD", "")
            logging.info("Using existing ShadowTLS Shadowsocks password.")
            if not ss_password:
                logging.info("Generating new ShadowTLS Shadowsocks password...")
                ss_password = secrets.token_urlsafe(16)
            os.environ["SHADOWTLS_SS_PASSWORD"] = ss_password
            logging.info(f"Adding ShadowTLS outbound {self.server_ip}:{port}...")
            stls_outbound, ss_outbound = self._stls(port=port, ss_password=ss_password)
            self.outbounds_config.outbounds.append(stls_outbound)
            self.outbounds_config.outbounds.append(ss_outbound)

    def write(self) -> None:
        self.outbounds_config.to_json(path=public_outbounds_path)
