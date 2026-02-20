from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, List

import yaml

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------

LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"

logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------

BASE_DIR = Path("./data")
TEST_DIR = Path("./test_data")
IPIFY_URL = "https://api.ipify.org"

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def log_function(func: Callable[..., Any]) -> Callable[..., Any]:
    """Log function entry and exit."""

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        # logger.debug("Entering %s", func.__name__)
        result = func(*args, **kwargs)
        # logger.debug("Exiting %s", func.__name__)
        return result

    return wrapper


def resolve_path(filename: str, local_mode: bool) -> Path:
    base = TEST_DIR if local_mode else BASE_DIR
    return base / filename


@log_function
def get_server_ip() -> str:
    result = subprocess.run(
        ["curl", "-s", IPIFY_URL],
        capture_output=True,
        text=True,
        check=True,
    )
    ip = result.stdout.strip()
    logger.info("Detected server IP: %s", ip)
    return ip


@log_function
def write_file(data: Dict[str, Any], filename: str, local_mode: bool = False) -> None:
    path = resolve_path(filename, local_mode)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


@log_function
def read_file(filename: str, as_type: str = "", local_mode: bool = False) -> Any:
    path = resolve_path(filename, local_mode)
    logger.info("Reading file %s", path)

    if local_mode:
        return _read_test_placeholder(filename, as_type)

    try:
        with path.open("r", encoding="utf-8") as f:
            match as_type:
                case "json":
                    return json.load(f)
                case "yaml":
                    return yaml.safe_load(f)
                case "lines":
                    return [line.rstrip("\n") for line in f]
                case _:
                    return f.read()
    except FileNotFoundError:
        logger.warning("File %s not found. Returning empty data.", path)
        raise


def _read_test_placeholder(filename: str, as_type: str) -> Any:
    match as_type:
        case "json" | "yaml":
            with open(filename, "r", encoding="utf-8") as f:
                return json.load(f) if as_type == "json" else yaml.safe_load(f)
        case "lines":
            return ["...", "...", "..."]
        case _:
            return "test-mode-placeholder"


@log_function
def read_env(
    name: str, default: str | int | None = None, *, required: bool = True
) -> str:
    value = os.environ.get(str(name), default)
    if required and not value:
        raise ValueError(f"Environment variable '{name}' is required but not set")
    logger.debug("Env %s=%s", name, value)
    return str(value) if value is not None else ""


@log_function
def env_is_true(name: str) -> bool:
    return read_env(name, default="false", required=False).lower() == "true"


# -----------------------------------------------------------------------------
# Config mutation helpers
# -----------------------------------------------------------------------------


def apply_bandwidth(
    obj: Dict[str, Any],
    up_env: str,
    down_env: str,
    up_default: int,
    down_default: int,
) -> None:
    if "up_mbps" in obj:
        obj["up_mbps"] = int(read_env(up_env, up_default))
    if "down_mbps" in obj:
        obj["down_mbps"] = int(read_env(down_env, down_default))


def update_tls_server_name(obj: Dict[str, Any], server_name: str) -> None:
    if obj.get("tls", {}).get("server_name") == "":
        obj["tls"]["server_name"] = server_name

    if obj.get("tls", {}).get("reality", {}).get("handshake", {}).get("server") == "":
        obj["tls"]["reality"]["handshake"]["server"] = server_name

    if obj.get("handshake", {}).get("server") == "":
        obj["handshake"]["server"] = server_name


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------


@log_function
def main(
    local_mode: bool = False,
    start_port: int = 8820,
    tls_server_name: str = "",
    obfs_password: str = "",
    up_mbps: int = 300,
    down_mbps: int = 300,
    up_mbps_factor: float = 0.1,
    down_mbps_factor: float = 0.1,
    **kwargs: Any,
) -> None:
    inbounds = read_file(
        kwargs.get("inbounds_template", "server.template.json"),
        "json",
        local_mode,
    ).get("inbounds", [])
    outbounds = read_file(
        kwargs.get("outbounds_template", "client.template.json"),
        "json",
        local_mode,
    ).get("outbounds", [])

    active_outbounds = [o for o in outbounds if not o.get("detour")]

    if len(inbounds) != len(active_outbounds):
        raise ValueError("The number of inbounds and outbounds mismatch")

    users = read_file(
        kwargs.get("uses_template", "users.yaml"),
        "yaml",
        local_mode,
    ).get("users", [])

    users_with_password = [
        {"name": u["name"], "password": u["password"]} for u in users
    ]

    users_with_flow: List[Dict[str, Any]] = [
        {"name": u["name"], "uuid": u["uuid"], "flow": "xtls-rprx-vision"}
        for u in users
    ]

    cert_chain = read_file(kwargs.get("certificate_path"), "lines", local_mode)
    ech_config = read_file(kwargs.get("ech_config_path"), "lines", local_mode)
    private_key = read_file(kwargs.get("private_key_path"), local_mode)
    public_key = read_file(kwargs.get("public_key_path"), local_mode)

    # -----------------------------
    # Server-side inbounds
    # -----------------------------

    for idx, inbound in enumerate(inbounds):
        inbound.setdefault("listen_port", start_port + idx)

        if "users" in inbound:
            match inbound.get("type"):
                case "tuic":
                    inbound["users"] = users
                case "vless":
                    inbound["users"] = users_with_flow
                case _:
                    if inbound.get("managed"):
                        continue
                    else:
                        inbound["users"] = users_with_password

        update_tls_server_name(inbound, tls_server_name)

        if inbound.get("tls", {}).get("reality", {}).get("private_key") == "":
            inbound["tls"]["reality"]["private_key"] = private_key

        if inbound.get("obfs", {}).get("password") == "":
            inbound["obfs"]["password"] = obfs_password

        apply_bandwidth(
            inbound,
            "INBOUND_UP_MBPS",
            "INBOUND_DOWN_MBPS",
            up_mbps,
            down_mbps,
        )

    # -----------------------------
    # Client-side outbounds
    # -----------------------------

    server_ip = get_server_ip()

    for idx, outbound in enumerate(active_outbounds):
        outbound["server"] = server_ip
        outbound["server_port"] = start_port + idx

        update_tls_server_name(outbound, tls_server_name)

        if outbound.get("tls", {}).get("certificate") == []:
            outbound["tls"]["certificate"] = cert_chain

        if outbound.get("tls", {}).get("reality", {}).get("public_key") == "":
            outbound["tls"]["reality"]["public_key"] = public_key

        if outbound.get("tls", {}).get("ech", {}).get("config") == []:
            outbound["tls"]["ech"]["config"] = ech_config

        if outbound.get("obfs", {}).get("password"):
            outbound["obfs"]["password"] = obfs_password

        apply_bandwidth(
            outbound,
            "OUTBOUND_UP_MBPS",
            "OUTBOUND_DOWN_MBPS",
            int(up_mbps * up_mbps_factor),
            int(down_mbps * down_mbps_factor),
        )

    # -----------------------------
    # Write output
    # -----------------------------

    write_file({"inbounds": inbounds}, kwargs.get("inbounds_output"), local_mode)
    write_file({"outbounds": outbounds}, kwargs.get("outbounds_output"), local_mode)
    write_file({"users": users}, kwargs.get("users_output"), local_mode)

    logger.info("Config generation completed successfully")
