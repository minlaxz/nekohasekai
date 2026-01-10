from typing import Any, Callable, Dict, List

import logging
import os
import json
import urllib.request
import yaml

from dotenv import load_dotenv, find_dotenv

if find_dotenv("sample.env"):
    load_dotenv(find_dotenv("sample.env"))


logging.basicConfig(
    level=logging.NOTSET,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

START_PORT = int(os.environ.get("START_PORT", 0))
TLS_SERVER_NAME = os.environ.get("TLS_SERVER_NAME", "")
OBFS_PASSWORD = os.environ.get("OBFS_PASSWORD", "")

list_sections = ["inbounds", "outbounds", "services", "endpoints"]
dict_sections = ["log", "dns"]


def __fetch_configs_wrapper(func: Callable[..., Any]) -> Callable[..., Any]:
    """:3"""

    def wrapper(**kwargs: Dict[str, Any]) -> Any:
        resp = json.load(urllib.request.urlopen("https://myip.wtf/json"))
        server_ip = resp.get("YourFuckingIPAddress")  # Fuck yeah!
        return func(**kwargs, server_ip=server_ip)

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
                logging.info(f"Updating {name} for tag: {tag}")
                deep_update(json_item, yaml_item)
    else:
        # log, dns, etc.
        yaml_section = config.get(name, {})
        if isinstance(yaml_section, dict):
            deep_update(json_config.get(name, {}), yaml_section)  # type: ignore

    with open(f"configs/{name}.json", "w") as f:
        json.dump(json_config, f, indent=2)


@__fetch_configs_wrapper
def main(**kwargs: Dict[str, Any]):
    server_ip = kwargs.get("server_ip", "")
    config: Dict[str, Any] = yaml.safe_load(open("config.yaml")) or {}
    users: Dict[str, Any] = yaml.safe_load(open("users.yaml")) or {}
    config["start_port"] = START_PORT
    config["users"] = users.get("users", [])

    start_port = config.get("start_port")
    if not start_port:
        logging.error("start_port is not specified.")
        return

    logging.info(f"Start Port (Clash API): {start_port}")
    logging.info(f"Server IP: {server_ip}")

    proxies_enabled: Dict[str, Any] = {}

    # Shadowsocks with SSM API and detour over ShadowTLS with user authentication
    proxies_enabled["shadowsocks"] = {"port": start_port + 1}
    proxies_enabled["shadowtls"] = {"port": start_port + 2}
    # Trojan with user authentication
    proxies_enabled["trojan"] = {"port": start_port + 3}
    # Hysteria2 with obfs with user authentication
    proxies_enabled["hysteria2"] = {"port": start_port + 4}

    tls_cert_path = "certs/certificate.crt"
    if not os.path.isfile(tls_cert_path):
        logging.error("Certificate path not specified in config.yaml.")
        return

    ech_config_path = "certs/ech.config"
    if not os.path.isfile(ech_config_path):
        logging.error("ECH config path not specified in config.yaml.")
        return

    logging.info(f"Enabled Proxies: {', '.join(proxies_enabled)}")
    config["inbounds"] = [
        {**i, "listen_port": proxies_enabled.get(i.get("tag", ""), {}).get("port")}
        for i in config.get("inbounds", [])
        if i.get("tag", "") in proxies_enabled.keys()
    ]

    for section in list_sections + dict_sections:
        load_and_update(config, section)
    logging.info("Done: Configured inbounds")

    # Client Outbounds
    certificate_array = [line.rstrip("\n") for line in open(tls_cert_path, "r")]
    ech_config_array = [line.rstrip("\n") for line in open(ech_config_path, "r")]

    with open("public/outbounds.json", "r") as f:
        outbounds: List[Dict[str, Any]] = [
            {**outbound}
            for outbound in json.load(f).get("outbounds", [])
            if outbound.get("type", "") in proxies_enabled
        ]
        for i in outbounds:
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

    logging.info("Configuration completed.")


if __name__ == "__main__":
    logging.info("Starting Sing-Box Config Generator")
    main()
