from typing import Dict, Any, List

import os
import json
import logging
import httpx
from datetime import datetime, timezone
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())
APP_UNSTABLE_OUTBOUNDS: List[str] = os.getenv("APP_UNSTABLE_OUTBOUNDS", "").split(",")
APP_IP_OUT_NAME: str = os.getenv("APP_IP_OUT_NAME", "IP-Out")
APP_OUT_NAME: str = os.getenv("APP_OUT_NAME", "Out")


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)


class Checker:
    def __init__(self, j: str, k: str, p: str, v: int) -> None:
        self.app_ssm_upstream = os.getenv("APP_SSM_UPSTREAM", "http://sing-box:8888")
        self.outbounds_path = os.getenv("APP_OUTBOUNDS_PATH", "outbounds.json")
        self.users_data_path = os.getenv("APP_USERS_DATA_PATH", "users.jsonc")
        self.template_path = (
            os.getenv("APP_TEMPLATE_v12_PATH", "test-data/sing-box-template")
            if v >= 12
            else os.getenv("APP_TEMPLATE_v11_PATH", "test-data/sing-box-template-v11")
        )
        self.route_path = os.getenv("APP_ROUTE_PATH", "test-data/route.json")
        self.outbounds_data: Dict[str, Any] = {}  # outbounds
        self.template_data: Dict[str, Any] = {}  # base config
        self.users_data: Dict[str, Any] = {}  # user data
        self.user_name = j
        self.user_psk = k
        self.version = v
        self.platform = p

        url = f"{self.app_ssm_upstream}/server/v1/users/{self.user_name}"
        try:
            response = httpx.get(url, timeout=5)
            response.raise_for_status()
            self.data = response.json()
            if self.data.get("uPSK") != self.user_psk:
                logging.error("User or PSK mismatch %s", self.user_name)
                raise Exception("User or PSK mismatch")
            else:
                downlinkBytes = self.data.get("downlinkBytes")
                uplinkBytes = self.data.get("uplinkBytes")
                if downlinkBytes + uplinkBytes > 30_000_000_000:
                    logging.error("Quota exceeded %s", self.user_name)
                    raise Exception("Quota exceeded")
                else:
                    logging.info("User %s verified successfully", self.user_name)
                    self._load_criticals()

        except (httpx.HTTPError, json.JSONDecodeError) as e:
            logging.error("Error fetching user data: %s", e)
            raise Exception("User verification failed")

        except Exception as e:
            logging.error("Error: %s", e)
            raise

    def _load_criticals(self):
        if self.template_path.startswith(("https://", "http://")):
            response = httpx.get(self.template_path, timeout=5)
            response.raise_for_status()
            self.template_data = response.json()
        else:
            with open(self.template_path, "r", encoding="utf-8") as file:
                self.template_data = json.load(file)

        if self.route_path.startswith(("https://", "http://")):
            response = httpx.get(self.route_path, timeout=5)
            response.raise_for_status()
            self.template_data["route"] = response.json().get("route", {})
        else:
            with open(self.route_path, "r", encoding="utf-8") as file:
                self.template_data["route"] = json.load(file).get("route", {})

        if self.outbounds_path.startswith(("https://", "http://")):
            response = httpx.get(self.outbounds_path, timeout=5)
            response.raise_for_status()
            self.outbounds_data = response.json()
        else:
            with open(self.outbounds_path, "r", encoding="utf-8") as file:
                self.outbounds_data = json.load(file)

        if self.users_data_path.startswith(("https://", "http://")):
            response = httpx.get(self.outbounds_path, timeout=5)
            response.raise_for_status()
            self.users_data = response.json()
        else:
            with open(self.users_data_path, "r", encoding="utf-8") as file:
                self.users_data = json.load(file)

        logging.info("Template and outbounds loaded successfully")


class Reader(Checker):
    def __init__(
        self,
        username: str,
        psk: str,
        version: int,
        platform: str,
        log_level: str,
        dns_host: str,
        dns_path: str,
        dns_detour: str,
        dns_final: str,
        dns_resolver: str,
        dns_version: int,
        route_detour: str,
        multiplex: bool,
        experimental: bool,
    ) -> None:
        super().__init__(username, psk, platform, version)
        self.log_level = log_level
        self.dns_host = dns_host
        self.dns_path = dns_path
        self.dns_detour = dns_detour
        self.dns_final = dns_final
        self.dns_resolver = dns_resolver
        self.dns_version = dns_version
        self.route_detour = route_detour
        self.multiplex = multiplex
        self.experimental = experimental

    def __inject_dns__(self) -> None:
        # Default: `dns-final` otherwise client provided
        # Values: dns-remote, dns-resolver, [dns-final]
        dns = self.template_data.get("dns", {})
        dns.update({
            "final": self.dns_final,
            "strategy": "ipv4_only" if self.dns_version == 4 else "prefer_ipv4",
        })

        # Mytel users in Myanmar may experience connectivity issues when using NextDNS DNS resolver.
        if self.version < 12 and self.experimental:
            dns_rules = dns.get("rules", [])
            dns_rules[0]["server"] = "dns-bypass"

        # Assuming APP_DNS_PATH ends with a trailing slash
        # e.g., /user_name
        # e.g., /custom_path/user_name
        dns_path = self.dns_path + self.user_name
        dns_servers = dns.get("servers", [])
        if self.version == 11:
            for i in dns_servers:
                if i.get("tag") == "dns-remote":
                    i.update({
                        "address": f"https://{self.dns_host}{dns_path}",
                        "address_strategy": "ipv4_only"
                        if self.dns_version == 4
                        else "prefer_ipv4",
                    })
                elif i.get("tag") == "dns-resolver":
                    # Client provided `dns_detour` i.e. `dd` and dns-resolver i.e. `dr`
                    i.update({
                        "address": self.dns_resolver,
                        "detour": self.dns_detour,
                    })
                elif i.get("tag") == "dns-bypass":
                    i.update({
                        "address": self.dns_resolver,
                    })
        else:
            for i in dns_servers:
                if i.get("tag") == "dns-remote":
                    i.update({
                        "server": self.dns_host,
                        "path": dns_path,
                        "domain_resolver": {
                            "server": "dns-resolver",
                            "strategy": "ipv4_only"
                            if self.dns_version == 4
                            else "prefer_ipv4",
                        },
                    })
                elif i.get("tag") == "dns-resolver":
                    # Client provided `dns_detour` i.e. `dd` and dns-resolver i.e. `dr`
                    i.update({
                        "server": self.dns_resolver,
                        "detour": self.dns_detour or i.get("detour"),
                    })
                elif i.get("tag") == "dns-bypass":
                    i.update({
                        "server": self.dns_resolver,
                    })

    def __inject_routes__(self) -> None:
        route: Dict[str, Any] = self.template_data.get("route", {})
        rule_set: List[Dict[str, Any]] = route.get("rule_set", [])
        rules: List[Dict[str, Any]] = route.get("rules", [])

        # Client provided `route_detour` i.e. `rd` for route download detour
        for i in rule_set:
            i.update({"download_detour": self.route_detour})

        # Mytel users in Myanmar may experience connectivity issues when using NextDNS DNS resolver.
        if self.version >= 12 and self.experimental:
            route["default_domain_resolver"] = "dns-bypass"

        # Rule 4, 6, 7
        rules[3]["outbound"] = APP_IP_OUT_NAME
        rules[6]["outbound"] = APP_OUT_NAME

    def __inject_outbounds__(self) -> None:
        outbounds: List[Dict[str, Any]] = []
        outbound_names: List[str] = []

        for i in self.outbounds_data["outbounds"]:
            if i.get("password") == "":
                i["password"] = self.user_psk

            if i.get("uuid") == "":
                i["uuid"] = next(
                    (
                        user["uuid"]
                        for user in self.users_data["users"]
                        if user["name"] == self.user_name
                    ),
                    "00000000-0000-0000-0000-000000000000",
                )

            # Remove multiplex from all outbounds by default
            # can still be enabled from client side with &?mx=true
            if not self.multiplex:
                _ = i.pop("multiplex", None)

            # Append all proxy outbounds
            outbounds.append(i)
            if i.get("tag") not in APP_UNSTABLE_OUTBOUNDS:
                outbound_names.append(i.get("tag"))

        outbounds.append({"type": "direct", "tag": "direct"})

        utc_now = datetime.now(timezone.utc)
        now = f"rev-{utc_now.year}{utc_now.month:02d}{utc_now.day:02d}"

        suffix = ".-."

        # Pullup outbounds
        outbounds.append({
            "type": "urltest",
            "tag": f"{now}{suffix}",
            "outbounds": outbound_names + ["direct"],
            "url": "https://www.gstatic.com/generate_204",
            "interval": "30s",
            "tolerance": 100,
        })

        # Outbounds
        outbounds.append({
            "type": "urltest",
            "tag": APP_IP_OUT_NAME,
            "outbounds": outbound_names,
            "url": "https://www.gstatic.com/generate_204",
            "interval": "30s",
            "tolerance": 100,
        })
        outbounds.append({
            "type": "urltest",
            "tag": APP_OUT_NAME,
            "outbounds": outbound_names,
            "url": "https://www.gstatic.com/generate_204",
            "interval": "30s",
            "tolerance": 100,
        })

        self.template_data["outbounds"] = outbounds

    def __inject_log__(self) -> None:
        log_level = self.log_level or self.template_data["log"]["level"]
        self.template_data["log"]["level"] = log_level

    def __inject_inbounds__(self) -> None:
        inbounds: List[Dict[str, Any]] = self.template_data.get("inbounds", [])
        for i in inbounds:
            if i.get("tag") == "tun-in":
                if self.dns_version != 4:
                    # Add IPv6 address to the template
                    i.get("address", []).append("fd00::1/126")

    def __inject_endpoints__(self) -> None:
        endpoints: List[Dict[str, Any]] = []
        self.template_data["endpoints"] = endpoints

    def unwarp(self) -> Dict[str, Any]:
        """
        Inject critical fields into the template and return the final config.
        """

        logging.info("Injecting fields into the template for user %s", self.user_name)
        self.__inject_dns__()
        self.__inject_log__()
        self.__inject_inbounds__()
        self.__inject_outbounds__()
        self.__inject_endpoints__()
        self.__inject_routes__()
        logging.info("Injection completed for user %s", self.user_name)
        return json.loads(json.dumps(self.template_data, ensure_ascii=False, indent=2))
