from typing import Dict

import secrets
import base64
import os
import logging
import json
import urllib.request

from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives import serialization

logging.basicConfig(
    level=logging.NOTSET,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)


def keys() -> Dict[str, str]:
    private_key = x25519.X25519PrivateKey.generate()
    private_key_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_key = private_key.public_key()
    public_key_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    private_key_b64 = base64.b64encode(private_key_bytes).decode()
    public_key_b64 = base64.b64encode(public_key_bytes).decode()
    return {
        "private": private_key_b64,
        "public": public_key_b64,
    }


def generate_password(length: int = 16) -> str:
    return secrets.token_urlsafe(length)[:length] + "=="


def get_password(key: str = "", length: int = 16) -> str:
    password = os.environ.get(key, "")
    if not password:
        logging.info(f"Generating new password for {key}...")
        return generate_password(length)
    logging.info(f"Using existing password for {key}.")
    return password


def get_server_ip() -> str:
    resp = json.load(urllib.request.urlopen("https://myip.wtf/json"))
    server_ip = resp.get("YourFuckingIPAddress")
    return server_ip
