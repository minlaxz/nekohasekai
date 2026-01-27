from typing import Any, Dict, List
import os
from dotenv import load_dotenv, find_dotenv
import json
import logging
import yaml

logging.basicConfig(
    level=logging.NOTSET,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

load_dotenv(find_dotenv("sample.env"))


def get_server_ip() -> str:
    response = os.popen("curl -s https://api.ipify.org").read().strip()
    if response:
        return response
    return ""


def write(data: Dict[str, Any], filename: str):
    with open(filename, "w") as f:
        json.dump(data, f, indent=2)
    logger.info(f"Wrote {filename}")


def main():
    start_port = int(os.getenv("START_PORT", "8810"))
    inbounds = []
    outbounds = []
    with open("configs/inbounds.json") as f:
        inbounds = json.load(f).get("inbounds", [])
    logger.info("Loaded inbounds.json")

    with open("public/outbounds.json") as f:
        outbounds = json.load(f).get("outbounds", [])
    logger.info("Loaded outbounds.json")

    with open("users.yaml") as f:
        users_w_uuid: List[Dict[str, Any]] = yaml.safe_load(f).get("users", [])
        users_wo_uuid = [
            {"name": u.get("name"), "password": u.get("password")} for u in users_w_uuid
        ]
    logger.info("Loaded users.yaml")

    with open("certs/certificate.crt", "r") as f:
        certificate_array = [line.rstrip("\n") for line in f]
    logger.debug("Loaded certificate array")

    with open("certs/ech.config", "r") as f:
        ech_config_array = [line.rstrip("\n") for line in f]
    logger.debug("Loaded ECH config array")

    for index, i in enumerate(inbounds):
        if i.get("listen_port") is not None:
            i["listen_port"] = start_port + index
        if i.get("users") is not None:
            if i.get("tag") == "tuic":
                i["users"] = users_w_uuid
            else:
                if i.get("managed") is True:
                    continue
                else:
                    i["users"] = users_wo_uuid
        if i.get("tls", {}).get("server_name") is not None:
            i["tls"]["server_name"] = os.getenv("TLS__SERVER_NAME")
        if i.get("handshake", {}).get("server") is not None:
            i["handshake"]["server"] = os.getenv("TLS__SERVER_NAME")
        if i.get("obfs", {}).get("password") is not None:
            i["obfs"]["password"] = os.getenv("HYSTERIA2__OBFS_PASSWORD")
        if i.get("up_mbps") is not None:
            i["up_mbps"] = int(os.getenv("INBOUND_UP_MBPS", 300))
        if i.get("down_mbps") is not None:
            i["down_mbps"] = int(os.getenv("INBOUND_DOWN_MBPS", 300))

    write({"inbounds": inbounds}, "configs/inbounds.json")

    for index, o in enumerate([o for o in outbounds if not o.get("detour")]):
        if o.get("server") is not None:
            o["server"] = get_server_ip()
        if o.get("server_port") is not None:
            o["server_port"] = start_port + index
        if o.get("tls", {}).get("server_name") is not None:
            o["tls"]["server_name"] = os.getenv("TLS__SERVER_NAME")
        if o.get("tls", {}).get("certificate") is not None:
            o["tls"]["certificate"] = certificate_array
        if o.get("tls", {}).get("ech", {}).get("config") is not None:
            o["tls"]["ech"]["config"] = ech_config_array
        if o.get("obfs", {}).get("password") is not None:
            o["obfs"]["password"] = os.getenv("HYSTERIA2__OBFS_PASSWORD")
        if o.get("up_mbps") is not None:
            o["up_mbps"] = int(os.getenv("OUTBOUND_UP_MBPS", 30))
        if o.get("down_mbps") is not None:
            o["down_mbps"] = int(os.getenv("OUTBOUND_DOWN_MBPS", 30))

    write({"outbounds": outbounds}, "public/outbounds.json")


if __name__ == "__main__":
    logger.info("Sing-Box Config Generation Started")
    main()
    logger.info("Sing-Box Config Generation Completed")
