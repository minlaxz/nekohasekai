from typing import Dict, Any, List

import os
import json
import logging
import httpx
from datetime import datetime, timezone

START_PORT: int = int(os.getenv("START_PORT", "8040"))
APP_LOCAL_JSON_PATH: str = os.getenv("APP_LOCAL_JSON_PATH", "outbounds.json")
APP_USERS_JSON_PATH: str = os.getenv("APP_USERS_JSON_PATH", "users.json")
APP_CF_JSON_PATH: str = os.getenv("APP_CF_JSON_PATH", "cloudflare.json")
APP_REMOTE_JSON_URL: str = os.getenv("APP_REMOTE_JSON_URL", "sing-box-template")
APP_CONFIG_HOST: str = os.getenv("APP_CONFIG_HOST", "")

# SSM
APP_SSM_SERVER: str = os.getenv("APP_SSM_SERVER", "nekohasekai")
END_PORT: int = int(os.getenv("END_PORT", ""))
SSM_UPSTREAM = f"http://{APP_SSM_SERVER}:{END_PORT}"

# Headscale
APP_HS_ENABLED: bool = os.getenv("APP_HS_ENABLED", "false").lower() == "true"
APP_HS_HOST: str = os.getenv("APP_HS_HOST", "")
APP_HS_API_KEY: str = os.getenv("APP_HS_API_KEY", "")
IS_HS_ENABLED = all([
    APP_HS_HOST,
    APP_HS_ENABLED,
    APP_HS_API_KEY,
])


TailscaleConfig: Dict[str, Any] = {
    "type": "tailscale",
    "tag": "hs-ep",
    "auth_key": "",
    "control_url": f"https://{APP_HS_HOST}",
    "hostname": "",
    "accept_routes": True,
    "udp_timeout": "5m0s",
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
        log_level: str,
        route_detour: str,
        multiplex: bool,
        experimental: bool,
        username: str,
        psk: str,
        please: bool = False,
    ) -> None:
        self.local_path = APP_LOCAL_JSON_PATH
        self.remote_url = APP_REMOTE_JSON_URL
        self.hs_url = f"https://{APP_HS_HOST}"
        self.app_config_host = APP_CONFIG_HOST

        self.users_path = APP_USERS_JSON_PATH
        self.cf_path = APP_CF_JSON_PATH

        self.platform = platform
        self.version = version
        self.log_level = log_level
        self.dns_host = dns_host
        self.dns_path = dns_path
        self.dns_detour = dns_detour
        self.dns_final = dns_final
        self.dns_resolver = dns_resolver
        self.route_detour = route_detour
        self.user_name = username
        self.user_psk = psk
        self.please = please
        self.multiplex = multiplex
        self.experimental = experimental

        self.local_data: Dict[str, Any] = {}
        self.remote_data: Dict[str, Any] = {}
        self.users_data: Dict[str, str] = {}
        self.cf_data: Dict[str, Any] = {}
        self.cf_enabled = False
        self.hs_data: Dict[str, Any] = {}
        self.hs_enabled = False

        self._load_local_data()
        self._load_remote_data()
        # Not for now.
        # self._load_users_data()
        self._load_cf_data()

        if self.version >= 12:
            self._fetch_hs_data()

    def _load_local_data(self):
        try:
            with open(self.local_path, "r", encoding="utf-8") as file:
                self.local_data = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError):
            self.local_data = {}

    def _load_users_data(self):
        try:
            with open(self.users_path, "r", encoding="utf-8") as file:
                # self.users_data => {"username": "psk"}
                self.users_data = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError):
            self.users_data = {}

    def _load_cf_data(self):
        try:
            with open(self.cf_path, "r", encoding="utf-8") as file:
                cf_data = json.load(file)
                # TODO: `others` will be replaced with individual user configs later
                self.cf_data = cf_data.get(self.user_name, cf_data.get("others", {}))
        except (FileNotFoundError, json.JSONDecodeError):
            self.cf_data = {}
        finally:
            self.cf_enabled = len(self.cf_data) > 0

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
                    logging.info(f"Headscale: got preAuthKeys: {preAuthKeys}")
                    key = preAuthKeys[-1].get("key", "")
                    logging.info(f"Headscale: used preAuthKey: {key}")
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
        dns.update({"final": self.dns_final})

        # Assuming APP_DNS_PATH ends with a trailing slash
        # e.g., /user_name
        # e.g., /custom_path/user_name
        dns_path = self.dns_path + self.user_name
        dns_servers = dns.get("servers", [])
        if self.version == 11:
            for i in dns_servers:
                if i.get("tag") == "dns-remote":
                    i.update({"address": f"https://{self.dns_host}{dns_path}"})
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
                5,
                {
                    "ip_cidr": ["100.64.0.0/24"],
                    "outbound": "hs-ep",
                },
            )

        if self.cf_enabled:
            route["final"] = "cf-ep"

    def __inject_outbounds__(self) -> None:
        outbounds: List[Dict[str, Any]] = [{"type": "direct", "tag": "direct"}]
        outbound_names: List[str] = ["direct"]
        excluded_outbound_names: List[str] = ["direct", "shadowsocks"]

        for i in self.local_data["outbounds"]:
            if i.get("tag") == "shadowsocks":
                # ! Overwrite psk for shadowsocks outbound if quota exceeded
                upsk = "invalid_psk_overwritten" if self.disabled else self.user_psk
                i["password"] = upsk

            # Remove multiplex from all outbounds by default
            # It can be enabled with ?mx=true
            if not self.multiplex:
                _ = i.pop("multiplex", None)

            if "exp" in i.get("tag"):
                if self.experimental:
                    outbounds.append(i)
                    outbound_names.append(i.get("tag"))
            else:
                outbounds.append(i)
                outbound_names.append(i.get("tag"))

        utc_now = datetime.now(timezone.utc)
        now = f"rev-{utc_now.year}{utc_now.month:02d}{utc_now.day:02d}"

        suffix = ""
        if self.hs_enabled:
            suffix += "hs"
            outbound_names.append("hs-ep")
            excluded_outbound_names.append("hs-ep")
        if self.cf_enabled:
            suffix += "cf"
            outbound_names.append("cf-ep")
            excluded_outbound_names.append("cf-ep")

        # Pullup outbounds
        outbounds.append({
            "type": "urltest",
            "tag": f"{now}-{suffix}",
            "outbounds": outbound_names,
            "url": "https://www.gstatic.com/generate_204",
            "interval": "30s",
            "tolerance": 100,
        })

        # Eco outbounds
        outbounds.append({
            "type": "urltest",
            "tag": "Out",
            "outbounds": [
                i for i in outbound_names if i not in excluded_outbound_names
            ],
            "url": f"https://{self.app_config_host}/generate_204?j={self.user_name}&k={self.user_psk}&expensive=false",
            "interval": "30s",
            "tolerance": 100,
        })

        self.remote_data["outbounds"] = outbounds

    def __inject_log__(self) -> None:
        log_level = self.log_level or self.remote_data["log"]["level"]
        self.remote_data["log"]["level"] = log_level

    def __inject_endpoints__(self) -> None:
        endpoints: list[dict[str, Any]] = []
        if self.cf_enabled:
            endpoints.append(self.cf_data)
        if self.hs_enabled:
            endpoint = TailscaleConfig.copy()
            endpoint["auth_key"] = self.hs_data.get("auth_key", "")
            endpoint["hostname"] = self.hs_data.get("hostname", "")
            endpoint["control_url"] = "https://" + endpoint["control_url"]
            endpoints.append(endpoint)
        self.remote_data["endpoints"] = endpoints

    def unwarp(self, disabled: bool = False) -> Dict[str, Any]:
        self.disabled: bool = disabled
        self.__inject_dns__()
        self.__inject_log__()
        self.__inject_endpoints__()
        self.__inject_outbounds__()
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
