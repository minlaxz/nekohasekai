from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import httpx
from fastapi import HTTPException

# -------------------------------------------------------------------
# Environment & Constants
# -------------------------------------------------------------------

APP_UNSTABLE_OUTBOUNDS: List[str] = [
    x for x in os.getenv("APP_UNSTABLE_OUTBOUNDS", "").split(",") if x
]
APP_TCP_OUT_NAME = os.getenv("APP_TCP_OUT_NAME", "TCP-Out")
APP_UDP_OUT_NAME = os.getenv("APP_UDP_OUT_NAME", "UDP-Out")
APP_SSM_UPSTREAM = os.getenv("APP_SSM_UPSTREAM", "http://sing-box:8888")

APP_DEFAULT_QUOTA_IN_BYTES = int(os.getenv("APP_DEFAULT_QUOTA_IN_BYTES", "30000000000"))
HTTP_TIMEOUT = 5  # seconds

# -------------------------------------------------------------------
# Logging
# -------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------


def load_json(source: str) -> Dict[str, Any]:
    """
    Load JSON from a local file or HTTP(S) URL.
    """
    if source.startswith(("http://", "https://")):
        response = httpx.get(source, timeout=HTTP_TIMEOUT)
        response.raise_for_status()
        return response.json()

    if not os.path.exists(source):
        raise FileNotFoundError(f"JSON source not found: {source}")

    with open(source, "r", encoding="utf-8") as f:
        return json.load(f)


# -------------------------------------------------------------------
# Checker
# -------------------------------------------------------------------


class Checker:
    def __init__(
        self,
        username: str,
        psk: str,
        platform: str,
        version: int,
    ) -> None:
        self.username = username
        self.psk = psk
        self.platform = platform
        self.version = version
        self.admin_mode = False

        self.app_ssm_upstream = os.getenv("APP_SSM_UPSTREAM", "http://sing-box:8888")
        self.outbounds_path = os.getenv(
            "APP_OUTBOUNDS_PATH", "test_data/outbounds.json"
        )
        self.users_data_path = os.getenv("APP_USERS_DATA_PATH", "test_data/users.jsonc")
        self.route_path = os.getenv("APP_ROUTE_PATH", "test_data/route")

        self.template_path = (
            os.getenv("APP_TEMPLATE_v12_PATH", "test_data/sing-box-template")
            if version >= 12
            else os.getenv("APP_TEMPLATE_v11_PATH", "test_data/sing-box-template-v11")
        )

        self.template_data: Dict[str, Any] = {}
        self.outbounds_data: Dict[str, Any] = {}
        self.users_data: Dict[str, Any] = {}

        self._verify_user()
        self._load_criticals()

        self.admin_mode = next(
            (
                u.get("admin", False)
                for u in self.users_data.get("users", [])
                if u.get("name") == self.username
            ),
            False,
        )

    # ------------------------------------------------------------------

    def _verify_user(self) -> None:
        url = f"{self.app_ssm_upstream}/server/v1/users/{self.username}"

        try:
            response = httpx.get(url, timeout=HTTP_TIMEOUT)
            response.raise_for_status()
            data = response.json()

            if data.get("uPSK") != self.psk:
                raise ValueError("User or PSK mismatch")

            used_bytes = data.get("uplinkBytes", 0) + data.get("downlinkBytes", 0)
            if used_bytes > APP_DEFAULT_QUOTA_IN_BYTES:
                raise ValueError("Quota exceeded")

            logger.info("User %s verified successfully", self.username)

        except Exception as exc:
            logger.error("User verification failed: %s", exc)
            # Invalidate PSK to prevent config generation
            self.psk = "invalid_psk"

    # ------------------------------------------------------------------

    def _load_criticals(self) -> None:
        self.template_data = load_json(self.template_path)
        route_data = load_json(self.route_path)
        self.template_data["route"] = route_data.get("route", {})

        self.outbounds_data = load_json(self.outbounds_path)
        self.users_data = load_json(self.users_data_path)

        if not self.template_data:
            raise RuntimeError("Template data is empty")

        logger.info("Template, routes, users, and outbounds loaded")


# -------------------------------------------------------------------
# Reader
# -------------------------------------------------------------------


class Reader(Checker):
    def __init__(
        self,
        username: str,
        psk: str,
        version: int,
        platform: str,
        log_level: Optional[str],
        dns_host: str,
        dns_path: str,
        dns_detour: str,
        dns_final: str,
        dns_resolver: str,
        dns_version: int,
        default_domain_resolver: str,
        route_detour: str,
        custom_rule_sets: str,
        custom_route_ips: str,
        multiplex: bool,
    ) -> None:
        super().__init__(username, psk, platform, version)

        self.log_level = log_level
        self.dns_host = dns_host
        self.dns_path = dns_path
        self.dns_detour = dns_detour
        self.dns_final = dns_final
        self.dns_resolver = dns_resolver
        self.dns_version = dns_version
        self.default_domain_resolver = default_domain_resolver
        self.route_detour = route_detour
        self.multiplex = multiplex
        self.custom_rule_sets = custom_rule_sets
        self.custom_route_ips = custom_route_ips

    # ------------------------------------------------------------------

    def _inject_dns(self) -> None:
        dns = self.template_data.setdefault("dns", {})

        dns["final"] = self.dns_final
        dns["strategy"] = "ipv4_only" if self.dns_version == 4 else "prefer_ipv4"

        dns_path = f"{self.dns_path}{self.username}"
        servers = dns.get("servers", [])

        for server in servers:
            tag = server.get("tag")
            match tag:
                case "dns-remote":
                    if self.version == 11:
                        server.update({
                            "address": f"https://{self.dns_host}{dns_path}",
                            "address_strategy": dns["strategy"],
                        })
                    else:
                        server.update({
                            "server": self.dns_host,
                            "path": dns_path,
                            "domain_resolver": {
                                "server": "dns-resolver",
                                "strategy": dns["strategy"],
                            },
                        })
                case "dns-resolver":
                    if self.version == 11:
                        server.update({
                            "address": self.dns_resolver,
                            "detour": self.dns_detour,
                        })
                    else:
                        server.update({
                            "server": self.dns_resolver,
                            "detour": self.dns_detour,
                        })
                case "dns-bypass":
                    if self.version == 11:
                        server.update({
                            "address": self.dns_resolver,
                        })
                    else:
                        server.update({
                            "server": self.dns_resolver,
                        })
                case _:
                    continue

    # ------------------------------------------------------------------

    def _inject_routes(self) -> None:
        route = self.template_data.get("route", {})
        rules = route.get("rules", [])

        owner = "minlaxz"
        repo = "nekohasekai"
        branch = "route-rules"

        api_url = f"https://api.github.com/repos/{owner}/{repo}/contents?ref={branch}"
        response = httpx.get(api_url, timeout=HTTP_TIMEOUT)
        response.raise_for_status()

        files = response.json()

        rule_sets: List[Any] = []
        geosite_rule_sets: List[Any] = []

        for file in files:
            if file["name"].endswith(".srs"):
                tag = file["name"].replace(".srs", "")
                rule_sets.append({
                    "tag": tag,
                    "type": "remote",
                    "format": "binary",
                    "url": f"https://cdn.jsdelivr.net/gh/{owner}/{repo}@{branch}/{file['name']}",
                    "download_detour": self.route_detour,
                    "update_interval": "1d",
                })
                geosite_rule_sets.append(tag)

        other_rule_sets = os.getenv("APP_DEFAULT_OTHER_RULE_SETS", "").split(",")
        for rule_set in other_rule_sets:
            rule_set = rule_set.strip()
            if rule_set and rule_set not in geosite_rule_sets:
                rule_sets.append({
                    "tag": rule_set,
                    "type": "remote",
                    "format": "binary",
                    "url": f"https://cdn.jsdelivr.net/gh/MetaCubeX/meta-rules-dat@sing/geo/geosite/{rule_set}.srs",
                    "download_detour": self.route_detour,
                    "update_interval": "1d",
                })
                geosite_rule_sets.append(rule_set)

        custom_rule_sets = self.custom_rule_sets.split(",")
        for rule_set in custom_rule_sets:
            rule_set = rule_set.strip()
            if rule_set and rule_set not in geosite_rule_sets:
                response = httpx.head(
                    f"https://cdn.jsdelivr.net/gh/MetaCubeX/meta-rules-dat@sing/geo/geosite/{rule_set}.srs",
                    timeout=HTTP_TIMEOUT,
                )
                if response.status_code == 200:
                    rule_sets.append({
                        "tag": rule_set,
                        "type": "remote",
                        "format": "binary",
                        "url": f"https://cdn.jsdelivr.net/gh/MetaCubeX/meta-rules-dat@sing/geo/geosite/{rule_set}.srs",
                        "download_detour": self.route_detour,
                        "update_interval": "1d",
                    })
                geosite_rule_sets.append(rule_set)

        route["rule_set"] = rule_sets

        if self.platform == "a":
            route["override_android_vpn"] = True

        if self.version > 11:
            # Version 11 doesn't support this option
            # * Overwrite default domain resolver if provided
            # Defaults to `dns-remote` to resovle jsdelivr CDN domains
            route["default_domain_resolver"] = self.default_domain_resolver

        # *This is a bit hacky, but this is it.
        rules[3]["outbound"] = APP_TCP_OUT_NAME
        rules[3]["rules"][1]["rules"][0]["rule_set"] = geosite_rule_sets
        if self.custom_route_ips:
            rules[3]["rules"][1]["rules"].append({
                "ip_cidr": [
                    ip.strip() + "/32"
                    for ip in self.custom_route_ips.split(",")
                    if ip.strip()
                ]
            })
        rules[4]["outbound"] = APP_UDP_OUT_NAME
        rules[4]["rules"][1]["rules"][0]["rule_set"] = geosite_rule_sets

        if self.admin_mode:
            logger.info("Injecting additional rules for admin user %s", self.username)
            rules.extend([
                {
                    "type": "logical",
                    "mode": "and",
                    "rules": [{"clash_mode": "Full"}, {"network": "tcp"}],
                    "outbound": APP_TCP_OUT_NAME,
                },
                {
                    "type": "logical",
                    "mode": "and",
                    "rules": [{"clash_mode": "Full"}, {"network": "udp"}],
                    "outbound": APP_UDP_OUT_NAME,
                },
            ])

    # ------------------------------------------------------------------

    def _inject_outbounds(self) -> None:
        result: List[Dict[str, Any]] = []
        stable_tags: List[str] = []
        tcp_tags: List[str] = []
        udp_tags: List[str] = []

        for ob in self.outbounds_data.get("outbounds", []):
            ob = ob.copy()

            if ob.get("password") == "":
                ob["password"] = self.psk

            if ob.get("uuid") == "":
                ob["uuid"] = next(
                    (
                        u["uuid"]
                        for u in self.users_data.get("users", [])
                        if u.get("name") == self.username
                    ),
                    "00000000-0000-0000-0000-000000000000",
                )

            if not self.multiplex:
                ob.pop("multiplex", None)

            result.append(ob)

            tag = ob.get("tag")
            if tag not in APP_UNSTABLE_OUTBOUNDS:
                stable_tags.append(tag)
                if any(x in tag for x in ("tcp", "uot")):
                    tcp_tags.append(tag)
                if any(x in tag for x in ("udp", "uot")):
                    udp_tags.append(tag)

        result.append({"type": "direct", "tag": "direct"})

        now = datetime.now(ZoneInfo("Asia/Yangon")).strftime(
            "→ %Y-%m-%d %H:%M:%S NO-IP"
        )

        for tag, targets in [
            (f"{now}", stable_tags + ["direct"]),
            (APP_TCP_OUT_NAME, tcp_tags),
            (APP_UDP_OUT_NAME, udp_tags),
        ]:
            result.append({
                "type": "urltest",
                "tag": tag,
                "outbounds": targets,
                "url": "https://www.gstatic.com/generate_204",
                "interval": "30s",
                "tolerance": 100,
            })

        self.template_data["outbounds"] = result

    # ------------------------------------------------------------------

    def _inject_log(self) -> None:
        self.template_data.setdefault("log", {})["level"] = (
            self.log_level or self.template_data["log"].get("level")
        )

    # ------------------------------------------------------------------

    def _inject_inbounds(self) -> None:
        for inbound in self.template_data.get("inbounds", []):
            if inbound.get("tag") == "tun-in" and self.dns_version != 4:
                inbound.setdefault("address", []).append("fd00::1/126")

    # ------------------------------------------------------------------

    def _inject_endpoints(self) -> None:
        self.template_data["endpoints"] = []

    # ------------------------------------------------------------------

    def unwarp(self) -> Dict[str, Any]:
        logger.info("Injecting config for user %s", self.username)

        self._inject_dns()
        self._inject_log()
        self._inject_inbounds()
        self._inject_outbounds()
        self._inject_endpoints()
        self._inject_routes()

        return json.loads(json.dumps(self.template_data, ensure_ascii=False, indent=2))


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
    async with httpx.AsyncClient(timeout=5) as client:
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
