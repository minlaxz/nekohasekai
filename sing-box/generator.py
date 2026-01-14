from typing import Any, Callable, Dict, List

import logging
import os
import json
import urllib.request
import yaml
import re
from pathlib import Path

logging.basicConfig(
    level=logging.NOTSET,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

list_sections = ["inbounds", "outbounds", "services", "endpoints"]
dict_sections = ["log", "dns"]


def __fetch_server_ip_wrapper(func: Callable[..., Any]) -> Callable[..., Any]:
    """:3"""

    def wrapper(**kwargs: Dict[str, Any]) -> Any:
        logger.debug("Fetching server public IPv4 address...")
        try:
            server_ip = json.load(
                urllib.request.urlopen("https://ipv4.myip.wtf/json", timeout=5)
            ).get("YourFuckingIPAddress")  # Fuck yeah!
            logger.info(f"Server public IP address: {server_ip}")
        except Exception as e:
            logger.error(f"Error fetching server public IPv4 address: {e}")
            server_ip = ""

        logger.debug("Fetching server public IPv6 address...")
        try:
            server_ip_6 = json.load(
                urllib.request.urlopen("https://ipv6.myip.wtf/json", timeout=5)
            ).get("YourFuckingIPAddress")
            logger.info(f"Server public IPv6 address: {server_ip_6}")
        except Exception as e:
            logger.error(f"Error fetching server public IPv6 address: {e}")
            server_ip_6 = ""

        return func(**kwargs, server_ip=server_ip, server_ip_6=server_ip_6)

    return wrapper


def deep_update(dst: Dict[str, Any], src: Dict[str, Any]):
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            deep_update(dst[k], v)  # type: ignore
        else:
            dst[k] = v


def load_and_update(config: Dict[str, Any] = {}, name: str = ""):
    with open(f"configs/{name}.json") as f:
        json_config = json.load(f)

    if name in list_sections:
        yaml_array = config.get(name, [])
        for json_item in json_config.get(name, []):
            tag = json_item.get("tag")
            yaml_item = next(
                (i for i in yaml_array if i.get("tag") == tag),
                None,
            )
            if yaml_item:
                # if json tag matches yaml tag, do a deep update
                logger.info(f"Updating {name} for tag: {tag}")
                deep_update(json_item, yaml_item)
    else:
        # log, dns, etc.
        yaml_section = config.get(name, {})
        if isinstance(yaml_section, dict):
            deep_update(json_config.get(name, {}), yaml_section)  # type: ignore

    with open(f"configs/{name}.json", "w") as f:
        json.dump(json_config, f, indent=2)


def update_env_file(key: str, value: str, file_path: str):
    env_path = Path(file_path)
    content = env_path.read_text()
    content = re.sub(
        rf"^{key}=.*$",
        f"{key}={value}",
        content,
        flags=re.MULTILINE,
    )
    env_path.write_text(content)
    logger.info(f"Updated {key} in {env_path}")


@__fetch_server_ip_wrapper
def main(**kwargs: Dict[str, Any]):
    with open("config.yaml") as f:
        config: Dict[str, Any] = yaml.safe_load(f) or {}
    logger.info("Loaded config.yaml")
    with open("users.yaml") as f:
        users: Dict[str, Any] = yaml.safe_load(f) or {}
    logger.info("Loaded users.yaml")

    # Log and verbosity level
    level = config.get("verbose", "").upper() if config.get("verbose") else "INFO"
    logger.setLevel(level)

    start_port = config.get("start_port", 0)
    end_port = config.get("end_port", 0)
    if not start_port and not end_port:
        logger.error("start_port and end_port are not specified.")
        return

    server_ip = kwargs.get("server_ip", "")
    server_ip_6 = kwargs.get("server_ip_6", "")
    logger.info(f"Start Port (Clash API): {start_port}")
    logger.info(f"End Port: {end_port}")
    logger.info(f"Server IP: {server_ip}")
    logger.info(f"Server IPv6: {server_ip_6}")

    user_list = users.get("users", [])
    logger.debug(f"Total users loaded: {len(user_list)}")
    config["users"].clear()
    config["users"].extend([
        {
            "name": u.get("name"),
            "password": u.get("password"),
        }
        for u in user_list
    ])
    config["users_with_uuid"].clear()
    config["users_with_uuid"].extend([
        {
            "name": u.get("name"),
            "password": u.get("password"),
            "uuid": u.get("uuid"),
        }
        for u in user_list
    ])

    proxies_enabled: Dict[str, Any] = {}

    # Shadowsocks with SSM API and detour over ShadowTLS with user authentication
    proxies_enabled["shadowsocks"] = {"port": start_port + 1}
    proxies_enabled["shadowtls"] = {"port": start_port + 2}
    # Trojan with user authentication
    proxies_enabled["trojan"] = {"port": start_port + 3}
    # Hysteria2 with obfs with user authentication
    proxies_enabled["hysteria2"] = {"port": start_port + 4}
    # TUIC with user authentication
    proxies_enabled["tuic"] = {"port": start_port + 5}

    tls_cert_path = "certs/certificate.crt"
    if not os.path.isfile(tls_cert_path):
        logger.error("Certificate path not specified in config.yaml.")
        return
    logger.info(f"TLS Certificate Path: {tls_cert_path}")

    ech_config_path = "certs/ech.config"
    if not os.path.isfile(ech_config_path):
        logger.error("ECH config path not specified in config.yaml.")
        return
    logger.info(f"ECH Config Path: {ech_config_path}")

    logger.info(f"Enabled Proxies: {', '.join(proxies_enabled)}")
    config["inbounds"] = [
        {**i, "listen_port": proxies_enabled.get(i.get("tag", ""), {}).get("port")}
        for i in config.get("inbounds", [])
        if i.get("tag", "") in proxies_enabled.keys()
    ]

    for section in list_sections + dict_sections:
        load_and_update(config, section)

    env_path = "sample.env" if config.get("debug", False) else ".env"
    # Update .env or sample.env
    update_env_file("START_PORT", config.get("start_port", ""), env_path)
    update_env_file("END_PORT", config.get("end_port", ""), env_path) # Also used as `WG_PORT`
    update_env_file("APP_CONFIG_HOST", config.get("server_name", ""), env_path)
    update_env_file("SERVER_IPv4", str(server_ip), env_path)
    update_env_file("SERVER_IPv6", str(server_ip_6), env_path)
    logger.info("Done: Configured inbounds")

    # Client Outbounds
    certificate_array = [line.rstrip("\n") for line in open(tls_cert_path, "r")]
    logger.debug("Loaded certificate array")
    ech_config_array = [line.rstrip("\n") for line in open(ech_config_path, "r")]
    logger.debug("Loaded ECH config array")

    with open("public/outbounds.json", "r") as f:
        outbounds: List[Dict[str, Any]] = [
            {**outbound}
            for outbound in json.load(f).get("outbounds", [])
            if outbound.get("type", "") in proxies_enabled
        ]
        for i in outbounds:
            logger.debug(f"Processing outbound: {i.get('tag', '')}")
            if i.get("server", None) == "" and i.get("server_port", None) == 0:
                i["server"] = server_ip
                i["server_port"] = proxies_enabled.get(i.get("tag", ""), {}).get("port")
            if i.get("tls", {}).get("certificate", None) == []:
                i["tls"]["certificate"] = certificate_array
            if i.get("tls", {}).get("ech", {}).get("config", None) == []:
                i["tls"]["ech"]["config"] = ech_config_array
            if i.get("tls", {}).get("server_name", None) == "":
                i["tls"]["server_name"] = config.get("tls_server_name", "")
            if i.get("obfs", {}).get("password", None) == "":
                i["obfs"]["password"] = config.get("obfs_password", "")

    with open("public/outbounds.json", "w") as f:
        json.dump({"outbounds": outbounds}, f, indent=2)
    logger.info("Done: Configured outbounds")

    logger.info("Configuration completed.")
    logger.info("You can now run 'docker compose up -d'!")


if __name__ == "__main__":
    logger.info("Starting Sing-Box Config Generator")
    main()
