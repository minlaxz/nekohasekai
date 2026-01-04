from typing import Any, Dict, List

import logging
import os
import argparse
import json
import urllib.request
import yaml

PORT_MARGIN = int(os.environ.get("PORT_MARGIN", 10))

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


def deep_update(dst: Dict[str, Any], src: Dict[str, Any]):
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            deep_update(dst[k], v)  # type: ignore
        else:
            dst[k] = v


def get_server_ip() -> str:
    resp = json.load(urllib.request.urlopen("https://myip.wtf/json"))
    server_ip = resp.get("YourFuckingIPAddress")  # Fuck yeah!
    return server_ip


def get_field(proxy_name: str, yaml_config: Dict[str, Any], field: str) -> str:
    inbounds = yaml_config.get("inbounds", [])
    for inbound in inbounds:
        if inbound.get("tag") == proxy_name:
            if field == "server_name":
                return inbound.get("tls", {}).get("server_name", "")
            elif field == "obfs_password":
                return inbound.get("obfs", {}).get("password", "")
    return ""


def load_and_update(config: Dict[str, Any] = {}, name: str = ""):
    with open(f"configs/{name}.json") as f:
        json_config = json.load(f)

    if name in ["inbounds", "services"]:
        yaml_inbounds = config.get(name, [])
        for json_item in json_config.get(name, []):
            tag = json_item.get("tag")
            yaml_item = next(
                (i for i in yaml_inbounds if i.get("tag") == tag),
                None,
            )
            if yaml_item:
                deep_update(json_item, yaml_item)
    else:
        yaml_section = config.get(name, {})
        if isinstance(yaml_section, dict):
            deep_update(json_config.get(name, {}), yaml_section)  # type: ignore

    with open(f"configs/{name}.json", "w") as f:
        json.dump(json_config, f, indent=2)


def main():
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
    is_ss_enabled = args.shadowsocks
    proxies_enabled.append("shadowsocks") if is_ss_enabled else None
    is_trojan_enabled = args.trojan
    proxies_enabled.append("trojan") if is_trojan_enabled else None
    is_hysteria2_enabled = args.hysteria2
    proxies_enabled.append("hysteria2") if is_hysteria2_enabled else None
    is_shadowtls_enabled = args.shadowtls
    proxies_enabled.append("shadowtls") if is_shadowtls_enabled else None

    # domain = os.environ.get("HANDSHAKE_DOMAIN", "")
    # reality_privatekey = os.environ.get("REALITY_PRIVATEKEY", "")
    # reality_publickey = os.environ.get("REALITY_PUBLICKEY", "")

    start_port = int(args.start_port)
    ssm_listen_port = int(args.end_port) or start_port + PORT_MARGIN
    if ssm_listen_port <= start_port + len(proxies_enabled):
        ssm_listen_port = start_port + PORT_MARGIN
        logging.warning(f"Port conflict, resetting `end_port` to {ssm_listen_port}")

    if not start_port:
        logging.error("Start port must be specified.")
        return

    if len(proxies_enabled) == 0:
        logging.error("No proxies are enabled.")
        return

    logging.info(f"Start Port (Clash API): {start_port}")
    logging.info(f"End Port (SSM API): {ssm_listen_port}")
    logging.info(f"Enabled Proxies: {', '.join(proxies_enabled)}")
    logging.info(f"Server IP: {get_server_ip()}")
    logging.info("Sing-Box configuration...")
    os.makedirs("public", exist_ok=True)

    clash_api_offset = 1  # in case clash api is enabled on `start_port`
    with open("config.yaml") as f:
        config: Dict[str, Any] = yaml.safe_load(f) or {}
        inbounds = config.get("inbounds", [])
        config["inbounds"] = [
            {**inbound, "listen_port": start_port + i + clash_api_offset}
            for i, inbound in enumerate(inbounds)
            if inbound.get("tag", "") in proxies_enabled
        ]
        services = config.get("services", [])
        config["services"] = [
            {**service, "listen_port": ssm_listen_port}
            for service in services
            if service.get("tag", "") == "ssm-api"
        ]
    for section in config:
        load_and_update(config, section)

    with open("certs/certificate.crt", "r") as cert_file:
        certificate_array = [line.rstrip("\n") for line in cert_file]

    with open("certs/ech.config", "r") as ech_file:
        ech_config_array = [line.rstrip("\n") for line in ech_file]

    with open("public/outbounds.json", "r") as f:
        outbounds = json.load(f).get("outbounds", [])
        outbounds = [
            {**outbound}
            for outbound in outbounds
            if outbound.get("tag", "") in proxies_enabled
        ]
        for i in outbounds:
            i["server_port"] = (
                start_port + proxies_enabled.index(i.get("tag", "")) + clash_api_offset
            )
            if i.get("tag") == "shadowsocks":
                i["server"] = get_server_ip()
            else:
                i["server"] = get_field(i.get("tag", ""), config, "server_name")
                i["certificate"] = certificate_array
                i["tls"]["ech"]["config"] = ech_config_array
                if i.get("tag") == "hysteria2":
                    i["obfs"]["password"] = get_field(
                        "hysteria2", config, "obfs_password"
                    )
    with open("public/outbounds.json", "w") as f:
        json.dump({"outbounds": outbounds}, f, indent=2)

    logging.info("Configuration completed.")


if __name__ == "__main__":
    logging.info("Starting Sing-Box Config Generator")
    main()
