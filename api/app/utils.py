from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Dict, List

import httpx
from fastapi import HTTPException

# -------------------------------------------------------------------
# Environment & Constants
# -------------------------------------------------------------------

APP_SSM_UPSTREAM = os.getenv("APP_INTERNAL_SSM_UPSTREAM", "http://sing-box:8888")
APP_CLIENT_DIR = os.getenv("APP_INTERNAL_CLIENT_DIR", "/sing-box/client")
APP_DEFAULT_QUOTA_IN_BYTES = int(os.getenv("APP_DEFAULT_QUOTA_IN_BYTES", "30000000000"))
HTTP_TIMEOUT = 5  # seconds

# Sections copied verbatim from APP_CLIENT_DIR; log/dns/outbounds get injected.
STATIC_SECTIONS = ("inbounds", "experimental", "endpoints", "services", "route")

logger = logging.getLogger(__name__)


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# -------------------------------------------------------------------
# Checker
# -------------------------------------------------------------------


class Checker:
    def __init__(self, username: str, psk: str) -> None:
        self.username = username
        self.psk = psk
        self._verify_user()

    def _verify_user(self) -> None:
        url = f"{APP_SSM_UPSTREAM}/server/v1/users/{self.username}"
        try:
            response = httpx.get(url, timeout=HTTP_TIMEOUT)
            response.raise_for_status()
            data = response.json()

            if data.get("uPSK") != self.psk:
                raise ValueError("User or PSK mismatch")

            used_bytes = data.get("uplinkBytes", 0) + data.get("downlinkBytes", 0)
            if used_bytes > APP_DEFAULT_QUOTA_IN_BYTES:
                raise ValueError("Quota exceeded")

            logger.info("User %s verified", self.username)
        except Exception as exc:
            logger.error("User verification failed: %s", exc)
            raise HTTPException(
                status_code=400, detail="User verification failed or quota exceeded."
            )


# -------------------------------------------------------------------
# Reader
# -------------------------------------------------------------------


class Reader(Checker):
    def __init__(
        self,
        username: str,
        psk: str,
        log_level: str,
        dns_host: str,
        dns_path: str,
        dns_detour: str,
        dns_final: str,
        dns_resolver: str,
        dns_version: int,
        multiplex: bool,
    ) -> None:
        super().__init__(username, psk)
        self.log_level = log_level
        self.dns_host = dns_host
        self.dns_path = dns_path
        self.dns_detour = dns_detour
        self.dns_final = dns_final
        self.dns_resolver = dns_resolver
        self.dns_version = dns_version
        self.multiplex = multiplex

    def _section(self, name: str) -> Any:
        return load_json(f"{APP_CLIENT_DIR}/{name}.json")[name]

    def _log(self) -> Dict[str, Any]:
        log = self._section("log")
        if self.log_level:
            log["level"] = self.log_level
        return log

    def _dns(self) -> Dict[str, Any]:
        dns = self._section("dns")
        strategy = "prefer_ipv4" if self.dns_version == 6 else "ipv4_only"
        if self.dns_final:
            dns["final"] = self.dns_final
        dns["strategy"] = strategy

        for server in dns.get("servers", []):
            match server.get("tag"):
                case "dns-remote":
                    server["server"] = self.dns_host
                    server["path"] = f"{self.dns_path}{self.username}"
                    server["domain_resolver"] = {
                        "server": "dns-resolver",
                        "strategy": strategy,
                    }
                case "dns-resolver":
                    server["server"] = self.dns_resolver
                    server["detour"] = self.dns_detour
                case "dns-resolver-bypass":
                    server["server"] = self.dns_resolver
        return dns

    def _outbounds(self) -> List[Dict[str, Any]]:
        outbounds = self._section("outbounds")
        for ob in outbounds:
            if ob.get("type") != "shadowsocks":
                continue  # shadowtls password is shared, set by entrypoint
            ob["password"] = self.psk
            if "multiplex" in ob:  # uot outbound has none: conflicts with multiplex
                ob["multiplex"]["enabled"] = self.multiplex
        return outbounds

    def unwarp(self) -> Dict[str, Any]:
        logger.info("Injecting config for user %s", self.username)
        config: Dict[str, Any] = {
            "log": self._log(),
            "dns": self._dns(),
            "outbounds": self._outbounds(),
        }
        for name in STATIC_SECTIONS:
            config[name] = self._section(name)
        return config


# -------------------------------------------------------------------
# Stats
# -------------------------------------------------------------------


def format_bytes(v: int) -> str:
    if v >= 1 << 30:
        return f"{v / (1 << 30):.2f} GB"
    elif v >= 1 << 20:
        return f"{v / (1 << 20):.2f} MB"
    elif v >= 1 << 10:
        return f"{v / (1 << 10):.2f} KB"
    return f"{v} B"


def format_packets(v: int) -> str:
    if v >= 1_000_000:
        return f"{v / 1_000_000:.2f} M"
    elif v >= 1_000:
        return f"{v / 1_000:.2f} K"
    return str(v)


async def get_stats() -> List[Dict[str, Any]]:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        stats_upstream = f"{APP_SSM_UPSTREAM}/server/v1/stats"
        users_upstream = f"{APP_SSM_UPSTREAM}/server/v1/users"

        try:
            stats_r, users_r = await asyncio.gather(
                client.get(stats_upstream),
                client.get(users_upstream),
            )
            stats_r.raise_for_status()
            users_r.raise_for_status()

            stats_data = stats_r.json()["users"]
            users_data = users_r.json()["users"]

            users_dict = {user["username"]: user for user in users_data}

            for stat in stats_data:
                username = stat["username"]
                if username in users_dict:
                    stat["uPSK"] = users_dict[username].get("uPSK")

            # sort by raw bytes
            stats_data.sort(key=lambda x: x.get("downlinkBytes", 0), reverse=True)  # type: ignore

            for row in stats_data:
                extra = {}
                for k, v in row.items():
                    if k.endswith("Bytes"):
                        extra[k + "Human"] = format_bytes(v)
                    elif k.endswith("Packets"):
                        extra[k + "Human"] = format_packets(v)

                row.update(extra)

            return stats_data

        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Upstream error: {str(e)}")
