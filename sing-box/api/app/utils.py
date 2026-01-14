from typing import Dict, Any, List

import os
import json
import logging
import httpx
from datetime import datetime, timezone
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())
START_PORT: int = int(os.getenv("START_PORT", "1080"))
END_PORT: int = int(os.getenv("START_PORT", "1090"))
APP_UNSTABLE_OUTBOUNDS: List[str] = os.getenv("APP_UNSTABLE_OUTBOUNDS", "").split(",")

# SSM
SSM_UPSTREAM = os.getenv("APP_SSM_UPSTREAM", "http://nekohasekai:8888")

# Headscale
APP_HS_ENABLED: bool = os.getenv("APP_HS_ENABLED", "false").lower() == "true"
APP_HS_API_KEY: str = os.getenv("APP_HS_API_KEY", "")
IS_HS_ENABLED = all([
    APP_HS_ENABLED,
    APP_HS_API_KEY,
])

APP_WG_ENABLED: bool = os.getenv("APP_WG_ENABLED", "false").lower() == "true"
APP_WG_USERNAME: str = os.getenv("APP_WG_USERNAME", "")
APP_WG_PASSWORD: str = os.getenv("APP_WG_PASSWORD", "")
IS_WG_ENABLED = all([
    APP_WG_ENABLED,
    APP_WG_USERNAME,
    APP_WG_PASSWORD,
])


TailscaleConfig: Dict[str, Any] = {
    "type": "tailscale",
    "tag": "hs-ep",
    "auth_key": "",
    "control_url": "",
    "hostname": "",
    "accept_routes": True,
    "udp_timeout": "5m0s",
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


class Loader:
    def __init__(
        self,
        platform: str,
        version: int,
        dns_host: str,
        dns_path: str,
        dns_detour: str,
        dns_final: str,
        dns_resolver: str,
        dns_version: int,
        log_level: str,
        route_detour: str,
        multiplex: bool,
        experimental: bool,
        username: str,
        psk: str,
        please: bool = False,
    ) -> None:
        self.remote_url = os.getenv("APP_REMOTE_JSON_URL", "")
        self.local_path = os.getenv("APP_LOCAL_JSON_PATH", "")
        # self.users_path = os.getenv("APP_LOCAL_USERS_PATH", "")
        self.cf_path = os.getenv("APP_LOCAL_CF_PATH", "")
        self.hs_url = os.getenv("APP_HS_UPSTREAM", "")
        self.wg_url = os.getenv("APP_WG_UPSTREAM", "")

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

        self.local_data: Dict[str, Any] = {}  # outbounds
        self.remote_data: Dict[str, Any] = {}  # base config
        self.user_data: Dict[str, Any] = {}  # user name and psk
        self.wg_enabled = False
        self.wg_data: Dict[str, Any] = {}  # wireguard config
        self.hs_enabled = False
        self.hs_data: Dict[str, Any] = {}  # headscale config

        self._load_local_data()
        self._load_remote_data()

        if IS_WG_ENABLED:
            self._load_wireguard_data()

        if self.version >= 12:
            self._fetch_hs_data()

    def _load_local_data(self):
        try:
            with open(self.local_path, "r", encoding="utf-8") as file:
                self.local_data = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logging.error("Error loading local outbounds.json: %s", e)

    def _load_remote_data(self):
        try:
            if self.remote_url.startswith("https://"):
                response = httpx.get(
                    self.remote_url + f"-v{self.version}"
                    if self.version == 11
                    else self.remote_url,
                    timeout=5,
                )
                response.raise_for_status()
                self.remote_data = response.json()
            else:
                with open(
                    self.remote_url + f"-v{self.version}"
                    if self.version == 1
                    else self.remote_url,
                    "r",
                    encoding="utf-8",
                ) as file:
                    self.remote_data = json.load(file)
        except (httpx.HTTPError, json.JSONDecodeError):
            self.remote_data = {}

    def _load_wireguard_data(self):
        try:
            auth = httpx.BasicAuth(username=APP_WG_USERNAME, password=APP_WG_PASSWORD)
            client = httpx.Client(auth=auth)
            wg_api = f"{self.wg_url}/api/client"
            response = client.get(wg_api, timeout=5)
            response.raise_for_status()
            users: List[Dict[str, Any]] = response.json()

            for u in users:
                if u.get("username") == self.user_name:
                    wg_api = wg_api + f"/{u.get('id')}"
                    response = client.get(wg_api, timeout=5)
                    response.raise_for_status()
                    self.wg_data = response.json()
                    self.wg_enabled = True
                    # * Force IPv6 when WireGuard is enabled
                    self.dns_version = 6
                    break
        except (httpx.HTTPError, json.JSONDecodeError):
            self.wg_data = {}
            self.wg_enabled = False

    def _fetch_hs_data(self):
        try:
            self.hs_data = {}
            if IS_HS_ENABLED:
                headers = {
                    "Authorization": f"Bearer {APP_HS_API_KEY}",
                }
                user_response = httpx.get(
                    f"{self.hs_url}/api/v1/user?name={self.user_name}",
                    timeout=3,
                    headers=headers,
                )
                user_response.raise_for_status()
                users = user_response.json().get("users", [])
                logging.info(f"Headscale: got users: {users}")
                if len(users) > 0:
                    user_id = int(users[0].get("id", 0))
                    response = httpx.get(
                        f"{self.hs_url}/api/v1/preauthkey?user={user_id}",
                        timeout=3,
                        headers=headers,
                    )
                    response.raise_for_status()
                    response.json()
                    preAuthKeys = response.json().get("preAuthKeys", [])
                    logging.info(
                        "Headscale: received %d preAuthKeys for user %s",
                        len(preAuthKeys),
                        self.user_name,
                    )
                    key = preAuthKeys[-1].get("key", "")
                    logging.info(
                        "Headscale: used preAuthKey for user %s", self.user_name
                    )
                    self.hs_data = {
                        "auth_key": key,
                        "hostname": f"{self.user_name}-ts",
                    }
        except (httpx.HTTPError, json.JSONDecodeError):
            self.hs_data = {}
        finally:
            self.hs_enabled = len(self.hs_data) > 0

    def __inject_dns__(self) -> None:
        # Default: `dns-final` otherwise client provided
        # Values: dns-remote, dns-resolver, [dns-final]
        dns = self.remote_data.get("dns", {})
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
                    # Client provided `dns_detour` i.e. `dd` for dns-resolver
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
                    # Client provided `dns_detour` i.e. `dd` for dns-resolver
                    i.update({
                        "server": self.dns_resolver,
                        "detour": self.dns_detour or i.get("detour"),
                    })

    def __inject_routes__(self) -> None:
        route: Dict[str, Any] = self.remote_data.get("route", {})
        rule_set: List[Dict[str, Any]] = route.get("rule_set", [])
        rules: List[Dict[str, Any]] = route.get("rules", [])

        # Client provided `route_detour` i.e. `rd` for route download detour
        for i in rule_set:
            i.update({"download_detour": self.route_detour})

        # Logs monitoring for routing error in client side
        # ws://100.64.0.x/logs, ws://100.64.0.x/connections
        if self.hs_enabled:
            rules.insert(
                2,
                {
                    "ip_cidr": ["100.64.0.0/24"],
                    "outbound": "hs-ep",
                },
            )

        if self.wg_enabled:
            rules.insert(
                3,
                {
                    "ip_cidr": ["10.8.0.0/24"],
                    "outbound": "wg-ep",
                },
            )
            rules.insert(
                4,
                {
                    "ip_version": 6,
                    "outbound": "wg-ep",
                },
            )

    def __inject_outbounds__(self) -> None:
        outbounds: List[Dict[str, Any]] = []
        outbound_names: List[str] = []

        for i in self.local_data["outbounds"]:
            # ! Overwrite psk if quota exceeded
            upsk = "invalid_psk_overwritten" if self.disabled else self.user_psk
            i["password"] = upsk

            # Remove multiplex from all outbounds by default
            # can still be enabled from client side with &?mx=true
            if not self.multiplex:
                _ = i.pop("multiplex", None)

            # Append all proxy outbounds
            outbounds.append(i)
            if i.get("tag") not in APP_UNSTABLE_OUTBOUNDS or "exp" not in i.get("tag"):
                outbound_names.append(i.get("tag"))

        outbounds.append({"type": "direct", "tag": "direct"})

        utc_now = datetime.now(timezone.utc)
        now = f"rev-{utc_now.year}{utc_now.month:02d}{utc_now.day:02d}"

        suffix = ""
        if self.hs_enabled:
            suffix += "-hs"

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
            "tag": "IP-Out",
            "outbounds": outbound_names,
            "url": "https://www.gstatic.com/generate_204",
            "interval": "30s",
            "tolerance": 100,
        })
        outbounds.append({
            "type": "urltest",
            "tag": "Out",
            "outbounds": outbound_names,
            "url": "https://www.gstatic.com/generate_204",
            "interval": "30s",
            "tolerance": 100,
        })

        self.remote_data["outbounds"] = outbounds

    def __inject_log__(self) -> None:
        log_level = self.log_level or self.remote_data["log"]["level"]
        self.remote_data["log"]["level"] = log_level

    def __inject_inbounds__(self) -> None:
        inbounds: List[Dict[str, Any]] = self.remote_data.get("inbounds", [])
        if self.dns_version == 4:
            for i in inbounds:
                if i.get("tag") == "tun-in":
                    i.get("address", []).pop(1)  # Remove IPv6 address

    def __inject_endpoints__(self) -> None:
        endpoints: list[dict[str, Any]] = []
        if self.wg_enabled:
            endpoint = WireguardConfig.copy()
            wg_peer_ip = os.getenv("SERVER_IPv4", "")
            wg_peer_public_key = os.getenv("APP_WG_PEER_PUBLIC_KEY", "")
            endpoint["private_key"] = self.wg_data.get("private_key", "")
            endpoint["address"] = [
                self.wg_data.get("ipv4Address", "") + "/32",
                self.wg_data.get("ipv6Address", "") + "/128",
            ]
            endpoint["private_key"] = self.wg_data.get("privateKey", "")
            endpoint["peers"][0]["address"] = wg_peer_ip
            endpoint["peers"][0]["port"] = os.getenv(
                "APP_WG_OVERRIDE_PORT", os.getenv("END_PORT")
            )
            endpoint["peers"][0]["public_key"] = wg_peer_public_key
            endpoint["peers"][0]["pre_shared_key"] = self.wg_data.get("preSharedKey")
            endpoints.append(endpoint)
        if self.hs_enabled:
            endpoint = TailscaleConfig.copy()
            endpoint["auth_key"] = self.hs_data.get("auth_key", "")
            endpoint["hostname"] = self.hs_data.get("hostname", "")
            endpoint["control_url"] = self.hs_url
            endpoints.append(endpoint)
        self.remote_data["endpoints"] = endpoints

    def unwarp(self, disabled: bool = False) -> Dict[str, Any]:
        self.disabled: bool = disabled
        self.__inject_dns__()
        self.__inject_log__()
        self.__inject_outbounds__()
        self.__inject_inbounds__()
        self.__inject_endpoints__()
        self.__inject_routes__()
        return json.loads(json.dumps(self.remote_data, ensure_ascii=False, indent=2))


class Checker(Loader):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

    def verify_key(self) -> bool:
        SSM_API = f"{SSM_UPSTREAM}/server/v1/users/{self.user_name}"
        try:
            response = httpx.get(SSM_API, timeout=5)
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
