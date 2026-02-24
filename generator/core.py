from __future__ import annotations

import yaml
import json
import os
import subprocess
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, List

import importlib.resources as resources

try:
    from .helpers import resolve_path, is_file_exists, logger
except ImportError:
    from helpers import resolve_path, is_file_exists, logger

# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------

PACKAGE_DIR = Path(__file__).resolve().parent
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


@log_function
def get_server_ip(local_mode: bool = False) -> str:
    if local_mode:
        ip = read_env("SERVER_IP", default="127.0.0.1", required=False)
        logger.info("Using local-mode server IP: %s", ip)
        return ip

    try:
        result = subprocess.run(
            ["curl", "-s", IPIFY_URL],
            capture_output=True,
            text=True,
            check=True,
        )
        ip = result.stdout.strip()
        if not ip:
            raise ValueError("Detected empty IP")
        logger.info("Detected server IP: %s", ip)
        return ip
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        fallback_ip = read_env("SERVER_IP", default="127.0.0.1", required=False)
        logger.warning(
            "Failed to detect server IP automatically. Using fallback: %s",
            fallback_ip,
        )
        return fallback_ip


@log_function
def write_file(data: Dict[str, Any], filename: str, local_mode: bool = False) -> None:
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


@log_function
def _load_package_resource(filename: str, as_type: str) -> Any:
    candidates = [
        resources.files(__package__).joinpath(filename),
        resources.files(__package__).joinpath("data").joinpath(filename),
    ]

    for candidate in candidates:
        try:
            with candidate.open("r", encoding="utf-8") as f:
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
            continue

    raise FileNotFoundError(filename)


def read_file(filename: str, as_type: str = "", local_mode: bool = False) -> Any:
    path = resolve_path(filename, local_mode)
    logger.info("Reading file %s", path)

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
        logger.warning("File %s not found on disk 🔎.", path)
        logger.info("Falling back to package data as default. 👍")
        try:
            return _load_package_resource(filename, as_type)
        except FileNotFoundError as exc:
            logger.exception("Required file %s not found.", path)
            raise FileNotFoundError(f"Required file {path} not found.") from exc


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


def update_certificate_paths(
    obj: Dict[str, Any],
    certificate_path: str,
    private_key_path: str,
    ech_key_path: str,
) -> None:
    if obj.get("tls", {}).get("key_path") == "":
        obj["tls"]["key_path"] = private_key_path
    if obj.get("tls", {}).get("certificate_path") == "":
        obj["tls"]["certificate_path"] = certificate_path

    if obj.get("tls", {}).get("ech", {}).get("key_path") == "":
        obj["tls"]["ech"]["key_path"] = ech_key_path


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
    certs_dir: str = "",
    inbounds_template: str = "",
    outbounds_template: str = "",
    users_template: str = "",
    **kwargs: Any,
) -> None:
    certificate_path = f"{certs_dir}/certificate.crt"
    private_key_path = f"{certs_dir}/private.key"
    ech_config_path = f"{certs_dir}/ech.config"
    ech_key_path = f"{certs_dir}/ech.key"
    r_private_key_path = f"{certs_dir}/reality_private.key"
    r_public_key_path = f"{certs_dir}/reality_public.key"

    for path in [
        certificate_path,
        private_key_path,
        ech_config_path,
        ech_key_path,
        r_private_key_path,
        r_public_key_path,
    ]:
        if not is_file_exists(path, local_mode):
            logger.critical(
                "Required file %s not found. Please run 'init' command first.", path
            )
            raise FileNotFoundError(
                f"Required file {path} not found. Please run 'init' command first."
            )

    cert_chain = read_file(certificate_path, "lines", local_mode)
    ech_config = read_file(ech_config_path, "lines", local_mode)
    r_private_key = read_file(r_private_key_path, local_mode=local_mode)
    r_public_key = read_file(r_public_key_path, local_mode=local_mode)

    inbounds_output = kwargs.get("inbounds_output", ".")
    outbounds_output = kwargs.get("outbounds_output", ".")
    users_output = kwargs.get("users_output", ".")

    inbounds = read_file(
        inbounds_template,
        "json",
        local_mode,
    ).get("inbounds", [])
    outbounds = read_file(
        outbounds_template,
        "json",
        local_mode,
    ).get("outbounds", [])

    active_outbounds = [o for o in outbounds if not o.get("detour")]

    if len(inbounds) != len(active_outbounds):
        raise ValueError("The number of inbounds and outbounds mismatch")

    users = read_file(
        users_template,
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
        update_certificate_paths(
            inbound, certificate_path, private_key_path, ech_key_path
        )

        if inbound.get("tls", {}).get("reality", {}).get("private_key") == "":
            inbound["tls"]["reality"]["private_key"] = r_private_key

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

    server_ip = get_server_ip(local_mode=local_mode)

    for idx, outbound in enumerate(active_outbounds):
        outbound["server"] = server_ip
        outbound["server_port"] = start_port + idx

        update_tls_server_name(outbound, tls_server_name)

        if outbound.get("tls", {}).get("certificate") == []:
            outbound["tls"]["certificate"] = cert_chain

        if outbound.get("tls", {}).get("reality", {}).get("public_key") == "":
            outbound["tls"]["reality"]["public_key"] = r_public_key

        if outbound.get("tls", {}).get("ech", {}).get("config") == []:
            outbound["tls"]["ech"]["config"] = ech_config

        if outbound.get("obfs", {}).get("password") == "":
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

    write_file({"inbounds": inbounds}, inbounds_output, local_mode)
    write_file({"outbounds": outbounds}, outbounds_output, local_mode)
    write_file({"users": users}, users_output, local_mode)

    logger.info("Config generation completed successfully")
