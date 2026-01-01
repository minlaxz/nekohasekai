from typing import Any, Dict, List

import argparse
import logging
import os
import yaml

from .common import (
    ServicesConfig,
    InboundsConfig,
    LogConfig,
    OutboundsConfig,
    RouteConfig,
    DNSConfig,
    ExperimentalConfig,
)
from .utils import get_server_info
from .constants import (
    conf_path,
    cache_path,
    conf_log_path,
    conf_outbounds_path,
    conf_route_path,
    conf_experimental_path,
    conf_dns_path,
    conf_inbounds_path,
    conf_services_path,
)
from ..typings.shadowsocks import ss_inbound

PORT_MARGIN = 10

logging.basicConfig(
    level=logging.NOTSET,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)


def main() -> None:
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
    proxies_enabled: List[str] = []
    proxies_enabled.append("shadowsocks") if args.shadowsocks else None
    proxies_enabled.append("trojan") if args.trojan else None
    proxies_enabled.append("hysteria2") if args.hysteria2 else None
    proxies_enabled.append("shadowtls") if args.shadowtls else None

    start_port = int(args.start_port)
    if not start_port:
        logging.error("Start port must be specified.")
        return

    ssm_listen_port = int(args.end_port) or start_port + PORT_MARGIN
    if ssm_listen_port <= start_port + len(proxies_enabled):
        ssm_listen_port = start_port + PORT_MARGIN
        logging.warning(f"Port conflict, overriding end_port to {ssm_listen_port}")

    if len(proxies_enabled) == 0:
        logging.error("No proxies are enabled.")
        return

    server_ip = get_server_info()[0]
    logging.info(f"Start Port (Clash API): {start_port}")
    logging.info(f"End Port (SSM API): {ssm_listen_port}")
    logging.info(f"Server IP: {server_ip}")
    logging.info(f"Enabled Proxies: {', '.join(proxies_enabled)}")
    logging.info("Generating Sing-Box configuration...")

    os.makedirs(conf_path, exist_ok=True)
    os.makedirs(cache_path, exist_ok=True)

    config: Dict[Any, Any] = {}
    with open(f"{cache_path}/inbounds.yaml", "w") as f:
        config = {
            "server": {
                "ip": server_ip,
                "start_port": start_port,
                "end_port": ssm_listen_port,
                "enabled_proxies": proxies_enabled,
            },
        }
        yaml.safe_dump(config, f)

    LogConfig().to_json(path=conf_log_path)
    OutboundsConfig().to_json(path=conf_outbounds_path)
    RouteConfig().to_json(path=conf_route_path)
    DNSConfig().to_json(path=conf_dns_path)
    clash_endpoint = f"127.0.0.1:{start_port}"
    exp_config = ExperimentalConfig()
    exp_config.experimental["clash_api"]["external_controller"] = clash_endpoint
    exp_config.to_json(path=conf_experimental_path)
    inbounds_config = InboundsConfig(inbounds=[])
    services_config = ServicesConfig(services=[])

    clash_offset = 1
    for index, proxy in enumerate(proxies_enabled):
        if proxy == "shadowsocks":
            ss, ssm = ss_inbound(
                port=start_port + index + clash_offset,
                ssm_port=ssm_listen_port,
            )
            inbounds_config.inbounds.append(ss)
            services_config.services.append(ssm)
            with open(f"{cache_path}/inbounds.yaml", "a") as f:
                yaml.safe_dump({"ssm": ssm}, f)
            with open(f"{cache_path}/inbounds.yaml", "a") as f:
                yaml.safe_dump({"shadowsocks": ss}, f)

    inbounds_config.to_json(path=conf_inbounds_path)
    services_config.to_json(path=conf_services_path)
    logging.info("Sing-Box configuration generation completed.")


if __name__ == "__main__":
    logging.info("Starting Sing-Box Config Generator")
    main()
