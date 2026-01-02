from typing import List

import argparse
import logging
import os

from common import (
    LogConfig,
    RouteConfig,
    ExperimentalConfig,
    DNSConfig,
    ServicesConfig,
    EndpointsConfig,
    InboundsConfig,
    OutboundsConfig,
    ClientOutboundsConfig,
)
from utils import get_password, get_server_ip
from trojan import generate as trojan_generate
from hysteria2 import generate as hy2_generate
from shadowsocks import generate as ss_generate
from shadowtls import generate as stls_generate

from constants import (
    conf_log_path,
    conf_outbounds_path,
    conf_route_path,
    conf_experimental_path,
    conf_dns_path,
    conf_inbounds_path,
    conf_services_path,
    conf_endpoints_path,
    public_outbounds_path,
)


logging.basicConfig(
    level=logging.NOTSET,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)


def main() -> None:
    server_ip = get_server_ip()

    parser = argparse.ArgumentParser(description="Sing-Box Config Generator Parser")
    parser.add_argument("--start-port", default=0, help="Starting port")
    parser.add_argument("--end-port", default=0, help="Ending port")
    parser.add_argument(
        "--shadowsocks",
        action="store_true",
        default=os.environ.get("SHADOWSOCKS", "false").lower() == "true",
        help="Shadowsocks",
    )
    parser.add_argument(
        "--trojan",
        action="store_true",
        default=os.environ.get("TROJAN", "false").lower() == "true",
        help="Trojan",
    )
    parser.add_argument(
        "--hysteria2",
        action="store_true",
        default=os.environ.get("HYSTERIA2", "false").lower() == "true",
        help="Hysteria2",
    )
    parser.add_argument(
        "--shadowtls",
        action="store_true",
        default=os.environ.get("SHADOWTLS", "false").lower() == "true",
        help="ShadowTLS",
    )
    args = parser.parse_args()

    port_margin = 10

    proxies_enabled: List[str] = []
    is_ss_enabled = args.shadowsocks
    proxies_enabled.append("shadowsocks") if is_ss_enabled else None
    is_trojan_enabled = args.trojan
    proxies_enabled.append("trojan") if is_trojan_enabled else None
    is_hysteria2_enabled = args.hysteria2
    proxies_enabled.append("hysteria2") if is_hysteria2_enabled else None
    is_shadowtls_enabled = args.shadowtls
    proxies_enabled.append("shadowtls") if is_shadowtls_enabled else None

    domain = os.environ.get("HANDSHAKE_DOMAIN", "")
    # reality_privatekey = os.environ.get("REALITY_PRIVATEKEY", "")
    # reality_publickey = os.environ.get("REALITY_PUBLICKEY", "")

    start_port = int(args.start_port)
    ssm_listen_port = int(args.end_port) or start_port + port_margin
    if ssm_listen_port <= start_port + len(proxies_enabled):
        ssm_listen_port = start_port + port_margin
        logging.warning(f"Port conflict, setting end_port to {ssm_listen_port}")

    if not start_port:
        logging.error("Start port must be specified.")
        return

    if len(proxies_enabled) == 0:
        logging.error("No proxies are enabled.")
        return
    logging.info(f"Enabled Proxies: {', '.join(proxies_enabled)}")

    logging.info(f"Start Port (Clash API): {start_port}")
    logging.info(f"End Port (SSM API): {ssm_listen_port}")
    logging.info(f"Server IP: {server_ip}")
    logging.info("Generating Sing-Box configuration...")

    os.makedirs("conf", exist_ok=True)
    os.makedirs("public", exist_ok=True)
    os.makedirs("cache", exist_ok=True)

    LogConfig().to_json(path=conf_log_path)
    OutboundsConfig().to_json(path=conf_outbounds_path)
    RouteConfig().to_json(path=conf_route_path)
    exp_config = ExperimentalConfig()
    exp_config.experimental["clash_api"]["external_controller"] = (
        f"0.0.0.0:{start_port}"
    )
    exp_config.to_json(path=conf_experimental_path)
    DNSConfig().to_json(path=conf_dns_path)
    inbounds_config = InboundsConfig(inbounds=[])
    services_config = ServicesConfig()
    endpoints_config = EndpointsConfig(endpoints=[])
    outbounds_config = ClientOutboundsConfig(outbounds=[])

    curr = start_port

    if is_ss_enabled:
        port = curr = curr + 1
        ss_generate(
            port,
            ssm_listen_port,
            server_ip,
            inbounds_config,
            outbounds_config,
            services_config,
        )
        services_config.to_json(path=conf_services_path)

    if is_trojan_enabled:
        port = curr = curr + 1
        password = get_password("TROJAN_PASSWORD", 16)
        trojan_generate(
            trojan_listen_port=port,
            trojan_password=password,
            server_name=domain,
            inbounds_config=inbounds_config,
            outbounds_config=outbounds_config,
        )

    if is_hysteria2_enabled:
        port = curr = curr + 1
        obfs = get_password("HYSTERIA2_OBFS_PASSWORD", 22)
        password = get_password("HYSTERIA2_PASSWORD", 22)
        hy2_generate(
            hysteria2_listen_port=port,
            hysteria2_obfs_password=obfs,
            hysteria2_password=password,
            server_name=domain,
            inbounds_config=inbounds_config,
            outbounds_config=outbounds_config,
        )

    if is_shadowtls_enabled:
        port = curr = curr + 1
        # Not necessary to be identical but for simplicity
        password = get_password("SHADOWTLS_PASSWORD", 16)
        stls_generate(
            shadowtls_listen_port=port,
            shadowtls_password=password,
            server_name=domain,
            server_ip=server_ip,
            inbounds_config=inbounds_config,
            outbounds_config=outbounds_config,
        )

    inbounds_config.to_json(path=conf_inbounds_path)
    endpoints_config.to_json(path=conf_endpoints_path)
    outbounds_config.to_json(path=public_outbounds_path)

    logging.info("Sing-Box configuration generation completed.")


if __name__ == "__main__":
    logging.info("Starting Sing-Box Config Generator")
    main()
