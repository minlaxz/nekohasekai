from typing import Any, Dict, List
import os
import sys
from dotenv import load_dotenv, find_dotenv
import json
import logging
import yaml
import subprocess

logging.basicConfig(
    level=logging.NOTSET,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

load_dotenv(find_dotenv("sing-box.env"))


def get_server_ip() -> str:
    response = subprocess.run(
        ["curl", "-s", "https://api.ipify.org"], capture_output=True, text=True
    ).stdout.strip()
    if response:
        return response
    return ""


def write(data: Dict[str, Any], filename: str):
    with open(filename, "w") as f:
        json.dump(data, f, indent=2)
    logger.info(f"Wrote {filename}")


def read(filename: str, as_type: str, debug: bool = False) -> Any:
    if not debug:
        with open(filename, "r") as f:
            if as_type == "json":
                return json.load(f)
            elif as_type == "yaml":
                return yaml.safe_load(f)
            elif as_type == "lines":
                return [line.rstrip("\n") for line in f]
    else:
        if as_type == "lines":
            return [
                "-----BEGIN-----",
                "...",
                "-----END-----",
            ]


def main():
    start_port = int(os.getenv("START_PORT", 8820))
    debug = os.getenv("DEBUG", "false").lower() == "true"
    if debug:
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)
    
    # Validate required environment variables
    tls_server_name = os.getenv("TLS__SERVER_NAME")
    if not tls_server_name:
        logger.error("TLS__SERVER_NAME environment variable is required but not set")
        sys.exit(1)
    
    hysteria2_obfs_password = os.getenv("HYSTERIA2__OBFS_PASSWORD")
    if not hysteria2_obfs_password:
        logger.error("HYSTERIA2__OBFS_PASSWORD environment variable is required but not set")
        sys.exit(1)
    
    inbounds = []
    outbounds = []
    users_w_uuid = []
    users_wo_uuid = []
    ssm_cache = {}
    certificate_array = []
    ech_config_array = []

    try:
        inbounds = read("configs/inbounds.json", "json").get("inbounds", [])
        logger.info("Loaded inbounds.json")

        outbounds = read("public/outbounds.json", "json").get("outbounds", [])
        logger.info("Loaded outbounds.json")

        users_w_uuid: List[Dict[str, Any]] = read("users.yaml", "yaml").get("users", [])
        users_wo_uuid = [
            {"name": u.get("name"), "password": u.get("password")} for u in users_w_uuid
        ]
        logger.info("Loaded users.yaml")

        certificate_array = read("certs/certificate.crt", "lines", debug=debug)
        logger.info("Loaded certificate array")

        ech_config_array = read("certs/ech.config", "lines", debug=debug)
        logger.info("Loaded ech.config array")

        ssm_cache = read("cache/ssm-cache.json", "json").get("ssm_cache", {})
        logger.info("Loaded ssm-cache.json")

    except FileNotFoundError:
        logger.error("File not found.")
        return

    user_with_0 = {user.get("name"): 0 for user in users_wo_uuid}
    ssm_cache["endpoints"]["/"]["global_uplink"] = 0
    ssm_cache["endpoints"]["/"]["global_downlink"] = 0
    ssm_cache["endpoints"]["/"]["global_uplink_packets"] = 0
    ssm_cache["endpoints"]["/"]["global_downlink_packets"] = 0
    ssm_cache["endpoints"]["/"]["global_tcp_sessions"] = 0
    ssm_cache["endpoints"]["/"]["global_udp_sessions"] = 0
    ssm_cache["endpoints"]["/"]["user_uplink"] = user_with_0
    ssm_cache["endpoints"]["/"]["user_downlink"] = user_with_0
    ssm_cache["endpoints"]["/"]["user_uplink_packets"] = user_with_0
    ssm_cache["endpoints"]["/"]["user_downlink_packets"] = user_with_0
    ssm_cache["endpoints"]["/"]["user_tcp_sessions"] = user_with_0
    ssm_cache["endpoints"]["/"]["user_udp_sessions"] = user_with_0
    ssm_cache["endpoints"]["/"]["users"] = {
        user.get("name"): user.get("password") for user in users_wo_uuid
    }

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
            i["tls"]["server_name"] = tls_server_name
        if i.get("handshake", {}).get("server") is not None:
            i["handshake"]["server"] = tls_server_name
        if i.get("obfs", {}).get("password") is not None:
            i["obfs"]["password"] = hysteria2_obfs_password
        if i.get("up_mbps") is not None:
            i["up_mbps"] = int(os.getenv("INBOUND_UP_MBPS", 300))
        if i.get("down_mbps") is not None:
            i["down_mbps"] = int(os.getenv("INBOUND_DOWN_MBPS", 300))

    for index, o in enumerate([o for o in outbounds if not o.get("detour")]):
        if o.get("server") is not None:
            o["server"] = get_server_ip()
        if o.get("server_port") is not None:
            o["server_port"] = start_port + index
        if o.get("tls", {}).get("server_name") is not None:
            o["tls"]["server_name"] = tls_server_name
        if o.get("tls", {}).get("certificate") is not None:
            o["tls"]["certificate"] = certificate_array
        if o.get("tls", {}).get("ech", {}).get("config") is not None:
            o["tls"]["ech"]["config"] = ech_config_array
        if o.get("obfs", {}).get("password") is not None:
            o["obfs"]["password"] = hysteria2_obfs_password
        if o.get("up_mbps") is not None:
            o["up_mbps"] = int(os.getenv("OUTBOUND_UP_MBPS", 30))
        if o.get("down_mbps") is not None:
            o["down_mbps"] = int(os.getenv("OUTBOUND_DOWN_MBPS", 30))

    write({"inbounds": inbounds}, "configs/inbounds.json")
    write({"outbounds": outbounds}, "public/outbounds.json")
    write({"ssm_cache": ssm_cache}, "cache/ssm-cache.json")


if __name__ == "__main__":
    logger.info("Sing-Box Config Generation Started")
    main()
    logger.info("Sing-Box Config Generation Completed")
