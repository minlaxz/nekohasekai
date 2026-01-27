from typing import Dict, Any, List

import os
import json
import logging
import httpx
from datetime import datetime, timezone
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())
START_PORT: int = int(os.getenv("START_PORT", "8810"))
END_PORT: int = int(os.getenv("END_PORT", "8820"))
APP_UNSTABLE_OUTBOUNDS: List[str] = os.getenv("APP_UNSTABLE_OUTBOUNDS", "").split(",")
APP_IP_OUT_NAME: str = os.getenv("APP_IP_OUT_NAME", "IP-Out")
APP_OUT_NAME: str = os.getenv("APP_OUT_NAME", "Out")

# Headscale
APP_HS_ENABLED: bool = os.getenv("APP_HS_ENABLED", "false").lower() == "true"
APP_HS_API_KEY: str = os.getenv("APP_HS_API_KEY", "")
APP_HS_CONTROL_URL: str = "https://" + os.getenv("APP_HS_HOST", "")
APP_HS_ADVERTISE_ROUTES: str = os.getenv("APP_HS_ADVERTISE_ROUTES", "")
IS_HS_ENABLED = all([
    APP_HS_ENABLED,
    APP_HS_API_KEY,
])

APP_WG_ENABLED: bool = os.getenv("APP_WG_ENABLED", "false").lower() == "true"
APP_WG_USERNAME: str = os.getenv("APP_WG_USERNAME", "")
APP_WG_PASSWORD: str = os.getenv("APP_WG_PASSWORD", "")
APP_WG_PEER_IPv4: str = os.getenv("APP_WG_PEER_IPv4", "")
APP_WG_PEER_PORT: int = int(os.getenv("APP_WG_PEER_PORT", os.getenv("END_PORT", 0)))
APP_WG_PEER_PUBLIC_KEY: str = os.getenv("APP_WG_PEER_PUBLIC_KEY", "")
IS_WG_ENABLED = all([
    APP_WG_ENABLED,
    APP_WG_USERNAME,
    APP_WG_PASSWORD,
    APP_WG_PEER_IPv4,
])


TailscaleConfig: Dict[str, Any] = {
    "type": "tailscale",
    "tag": "hs-ep",
    "auth_key": "",
    "control_url": "",
    "hostname": "",
    "accept_routes": True,
    "udp_timeout": "5m0s",
    "advertise_routes": [],
}

WireguardConfig: Dict[str, Any] = {
    "type": "wireguard",
    "tag": "wg-ep",
    "system": False,
    "mtu": 1280,
    "address": [],
    "private_key": "",
    "peers": [
        {
            "address": "",
            "port": 0,
            "public_key": "",
            "pre_shared_key": "",
            "allowed_ips": ["0.0.0.0/0", "::/0"],
            "persistent_keepalive_interval": 0,
            "reserved": [0, 0, 0],
        }
    ],
    "workers": 2,
    "detour": "",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)


class Reader:
    def __init__(
        self,
        username: str,
        psk: str,
        please: bool,
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
        self.template_path = (
            os.getenv("APP_TEMPLATE_v12_PATH", "")
            if version >= 12
            else os.getenv("APP_TEMPLATE_v11_PATH", "")
        )
        self.outbounds_path = os.getenv("APP_OUTBOUNDS_PATH", "")
        self.app_ssm_upstream = os.getenv("APP_SSM_UPSTREAM", "http://nekohasekai:8888")
        self.app_hs_upstream = os.getenv("APP_HS_UPSTREAM", "http://headscale:8080")
        self.app_wg_upstream = os.getenv("APP_WG_UPSTREAM", "http://wg-easy:51821")

        self.platform = platform
        self.version = version
        self.log_level = log_level
        self.dns_host = dns_host
        self.dns_path = dns_path
        self.dns_detour = dns_detour
        self.dns_final = dns_final
        self.dns_resolver = dns_resolver
        self.dns_version = dns_version
        self.route_detour = route_detour
        self.user_name = username
        self.user_psk = psk
        self.please = please
        self.multiplex = multiplex
        self.experimental = experimental

        self.outbounds_data: Dict[str, Any] = {}  # outbounds
        self.template_data: Dict[str, Any] = {}  # base config
        self.has_critical_error: bool = False
        self._load_criticals()

        self.wg_enabled = False
        self.wg_data: Dict[str, Any] = WireguardConfig.copy()
        # Server side supports WireGuard integration
        if IS_WG_ENABLED and self.version >= 11:
            self.app_wg_peer_ipv4 = APP_WG_PEER_IPv4
            self.app_wg_peer_port = APP_WG_PEER_PORT
            self.app_wg_peer_public_key = APP_WG_PEER_PUBLIC_KEY
            # Load WireGuard data if client exists
            self._load_wireguard_data()

        self.hs_enabled = False
        self.hs_data: Dict[str, Any] = TailscaleConfig.copy()
        # Server side supports Headscale integration
        if IS_HS_ENABLED and self.version >= 12:
            self.app_hs_control_url = APP_HS_CONTROL_URL
            self.app_hs_advertise_routes = (
                APP_HS_ADVERTISE_ROUTES.split(",") if APP_HS_ADVERTISE_ROUTES else []
            )
            # Load Headscale data if client exists
            self._load_headscale_data()

    def _load_criticals(self):
        try:
            if self.template_path.startswith(("https://", "http://")):
                response = httpx.get(
                    self.template_path,
                    timeout=5,
                )
                response.raise_for_status()
                self.template_data = response.json()
            else:
                with open(
                    self.template_path,
                    "r",
                    encoding="utf-8",
                ) as file:
                    self.template_data = json.load(file)

            with open(self.outbounds_path, "r", encoding="utf-8") as file:
                self.outbounds_data = json.load(file)

        except Exception as e:
            logging.error("Error loading data: %s", e)
            self.has_critical_error = True
            self.template_data = {}
            self.outbounds_data = {}

    def _load_wireguard_data(self):
        try:
            auth = httpx.BasicAuth(username=APP_WG_USERNAME, password=APP_WG_PASSWORD)
            wg_api = f"{self.app_wg_upstream}/api"
            client = httpx.Client(base_url=wg_api, auth=auth, timeout=5)
            user_r = client.get("/client")
            user_r.raise_for_status()
            users: List[Dict[str, Any]] = user_r.json()
            for u in users:
                if u.get("name") == self.user_name:
                    config_r = client.get(f"/client/{u.get('id')}")
                    config_r.raise_for_status()
                    config = config_r.json()
                    self.wg_data["privateKey"] = config.get("privateKey", "")
                    self.wg_data["address"] = [
                        config.get("ipv4Address", "") + "/32",
                        config.get("ipv6Address", "") + "/128",
                    ]
                    self.wg_data["peers"][0]["persistent_keepalive_interval"] = 10
                    self.wg_data["peers"][0]["address"] = self.app_wg_peer_ipv4
                    self.wg_data["peers"][0]["port"] = self.app_wg_peer_port
                    self.wg_data["peers"][0]["public_key"] = self.app_wg_peer_public_key
                    self.wg_data["peers"][0]["pre_shared_key"] = config.get(
                        "preSharedKey"
                    )
                    self.wg_data["detour"] = "IP-Out"
                    self.wg_enabled = True
                    # * Force IPv6 when WireGuard is enabled
                    # self.dns_version = 6
                    break
        except Exception as e:
            logging.error(f"WG: error fetching data for {self.user_name}: {e}")

    def _load_headscale_data(self):
        try:
            headers = {"Authorization": f"Bearer {APP_HS_API_KEY}"}
            client = httpx.Client(headers=headers, timeout=5)
            hs_api = f"{self.app_hs_upstream}/api/v1"
            user_r = client.get(f"{hs_api}/user?name={self.user_name}")
            user_r.raise_for_status()
            users = user_r.json().get("users", [])
            logging.info(f"HS: got total user(s) for {self.user_name}: {len(users)}")
            if len(users) > 0:
                user_id = int(users[0].get("id", 0))
                key_r = client.get(f"{hs_api}/preauthkey?user={user_id}")
                key_r.raise_for_status()
                key_r.json()
                keys = key_r.json().get("preAuthKeys", [])
                logging.info(f"HS: got {len(keys)} for user {self.user_name}")
                self.hs_data["auth_key"] = keys[-1].get("key", "")
                self.hs_data["hostname"] = self.user_name + "-ts"
                self.hs_data["control_url"] = self.app_hs_control_url
                self.hs_data["advertise_routes"] = self.app_hs_advertise_routes
                self.hs_enabled = True
            else:
                logging.warning(f"HS: user {self.user_name} not found")
        except Exception as e:
            logging.error(f"HS: error fetching data for {self.user_name}: {e}")

    def __inject_dns__(self) -> None:
        # Default: `dns-final` otherwise client provided
        # Values: dns-remote, dns-resolver, [dns-final]
        dns = self.template_data.get("dns", {})
        dns.update({
            "final": self.dns_final,
            "strategy": "ipv4_only" if self.dns_version == 4 else "prefer_ipv4",
        })

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

    def __inject_routes__(self) -> None:
        route: Dict[str, Any] = self.template_data.get("route", {})
        rule_set: List[Dict[str, Any]] = route.get("rule_set", [])
        rules: List[Dict[str, Any]] = route.get("rules", [])

        # Client provided `route_detour` i.e. `rd` for route download detour
        for i in rule_set:
            i.update({"download_detour": self.route_detour})

        # Rule 4, 6, 7
        rules[3]["outbound"] = APP_IP_OUT_NAME
        rules[6]["outbound"] = APP_OUT_NAME
        rules[7]["outbound"] = APP_OUT_NAME

        # Logs monitoring for routing error in client side
        # ws://100.64.0.x/logs, ws://100.64.0.x/connections
        if self.hs_enabled:
            # Now rules will become 9 in total.
            rules.insert(
                3,
                {
                    "ip_cidr": ["100.64.0.0/24"],
                    "outbound": "hs-ep",
                },
            )

        if self.wg_enabled:
            # Now rules will become 10 in total if `hs_enabled` 9 otherwise.
            rules.insert(
                4,
                {
                    "type": "logical",
                    "mode": "or",
                    "rules": [
                        {"ip_cidr": ["10.8.0.0/24"]},
                        {"ip_version": 6},
                    ],
                    "outbound": "wg-ep",
                },
            )

    def __inject_outbounds__(self) -> None:
        outbounds: List[Dict[str, Any]] = []
        outbound_names: List[str] = []

        for i in self.outbounds_data["outbounds"]:
            # ! Overwrite psk if quota exceeded
            upsk = "invalid_psk_overwritten" if self.disabled else self.user_psk
            i["password"] = upsk

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

        suffix = "-"
        if self.hs_enabled:
            suffix += "hs"
        if self.wg_enabled:
            suffix += "wg"

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
                # Add IPv6 address to the template
                if self.dns_version == 6:
                    i.get("address", []).append("fd00::1/126")

    def __inject_endpoints__(self) -> None:
        endpoints: list[dict[str, Any]] = []
        if self.wg_enabled:
            endpoints.append(self.wg_data)
        if self.hs_enabled:
            endpoints.append(self.hs_data)
        self.template_data["endpoints"] = endpoints

    def unwarp(self, disabled: bool = False) -> Dict[str, Any]:
        self.disabled: bool = disabled
        self.__inject_dns__()
        self.__inject_log__()
        self.__inject_inbounds__()
        self.__inject_outbounds__()
        self.__inject_endpoints__()
        self.__inject_routes__()
        return json.loads(json.dumps(self.template_data, ensure_ascii=False, indent=2))


class Checker(Reader):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

    def verify_key(self) -> bool:
        url = f"{self.app_ssm_upstream}/server/v1/users/{self.user_name}"
        try:
            response = httpx.get(url, timeout=5)
            response.raise_for_status()
            self.data = response.json()
            if self.data.get("uPSK") == self.user_psk:
                return True
            else:
                raise Exception
        except (httpx.HTTPError, json.JSONDecodeError, Exception):
            return False

    def is_quota_limited(self):
        return self.please or (
            self.data.get("downlinkBytes") + self.data.get("uplinkBytes")
            > 30_000_000_000
        )  # 30 GB Limits or not pleasing :3

    def unwarp(self, disabled: bool = False) -> Dict[str, Any]:
        return super().unwarp(disabled=self.is_quota_limited())
