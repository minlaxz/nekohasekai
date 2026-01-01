from typing import Dict, Any, List

import os
import json
import logging
import httpx
import datetime

START_PORT: int = int(os.getenv("START_PORT", "8040"))
APP_LOCAL_JSON_PATH: str = os.getenv("APP_LOCAL_JSON_PATH", "outs.json")
APP_REMOTE_JSON_URL: str = os.getenv("APP_REMOTE_JSON_URL", "sing-box-template")
APP_CONFIG_HOST: str = os.getenv("APP_CONFIG_HOST", "")

# SSM
APP_SSM_SERVER: str = os.getenv("APP_SSM_SERVER", "nekohasekai")
END_PORT: int = int(os.getenv("END_PORT", ""))
SSM_UPSTREAM = f"http://{APP_SSM_SERVER}:{END_PORT}"

# Wireguard
APP_WG_ENABLED: bool = os.getenv("APP_WG_ENABLED", "false").lower() == "true"
APP_WG_SERVER: str = os.environ.get("APP_WG_SERVER", "")
APP_WG_SERVER_PORT: str = os.environ.get("APP_WG_SERVER_PORT", "")
APP_WG_PUBLIC_KEY: str = os.getenv("APP_WG_PUBLIC_KEY", "")
APP_WG_SERVER_USERNAME: str = os.getenv("APP_WG_SERVER_USERNAME", "")
APP_WG_SERVER_PASSWORD: str = os.getenv("APP_WG_SERVER_PASSWORD", "")
IS_WG_ENABLED = all([
    APP_WG_ENABLED,
    APP_WG_SERVER,
    APP_WG_SERVER_PORT,
    APP_WG_PUBLIC_KEY,
    APP_WG_SERVER_USERNAME,
    APP_WG_SERVER_PASSWORD,
])
WG_UPSTREAM = f"http://{APP_WG_SERVER}:{APP_WG_SERVER_PORT}"

# Headscale
APP_HS_ENABLED: bool = os.getenv("APP_HS_ENABLED", "false").lower() == "true"
APP_HS_SERVER: str = os.getenv("APP_HS_SERVER", "")
APP_HS_SERVER_PORT: str = os.getenv("APP_HS_SERVER_PORT", "")
APP_HS_HOST: str = os.getenv("APP_HS_HOST", "")
APP_HS_API_KEY: str = os.getenv("APP_HS_API_KEY", "")
IS_HS_ENABLED = all([
    APP_HS_ENABLED,
    APP_HS_SERVER,
    APP_HS_SERVER_PORT,
    APP_HS_API_KEY,
])

HS_UPSTREAM = (
    f"https://{APP_HS_HOST}"
    if APP_HS_HOST
    else f"http://{APP_HS_SERVER}:{APP_HS_SERVER_PORT}"
)

day = datetime.datetime.now(datetime.timezone.utc).day
month = datetime.datetime.now(datetime.timezone.utc).month
year = datetime.datetime.now(datetime.timezone.utc).year

WireguardConfig: Dict[str, Any] = {
    "type": "wireguard",
    "tag": "wg",
    "system": False,
    "name": "",
    "mtu": 1280,
    "address": [],
    "private_key": "",
    "detour": "Eco-Out",
    "peers": [
        {
            "address": "",
            "port": 0,
            "public_key": "",
            "pre_shared_key": "",
            "allowed_ips": ["0.0.0.0/0", "::/0"],
            "persistent_keepalive_interval": 25,
            "reserved": [0, 0, 0],
        }
    ],
}

TailscaleConfig: Dict[str, Any] = {
    "type": "tailscale",
    "tag": "ts",
    "auth_key": "",
    "control_url": os.getenv("HS_HOST", ""),
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
        self.app_config_host = APP_CONFIG_HOST
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
        self.wg_data: Dict[str, Any] = {}
        self.hs_data: Dict[str, Any] = {}
        self.wg_enabled = False
        self.hs_enabled = False
        self.__server_ip: str = ""
        self._load_local_data()
        self._load_remote_data()
        if self.version >= 12:
            self._fetch_hs_data()

    def _load_local_data(self):
        try:
            with open(self.local_path, "r", encoding="utf-8") as file:
                self.local_data = json.load(file)
                self.__server_ip = self.local_data.get("outbounds", [])[0].get(
                    "server", ""
                )
        except (FileNotFoundError, json.JSONDecodeError):
            self.local_data = {}

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

    def fetch_wg_data(self):
        try:
            self.wg_data = {}
            if IS_WG_ENABLED:
                auth = httpx.BasicAuth(
                    username=APP_WG_SERVER_USERNAME, password=APP_WG_SERVER_PASSWORD
                )
                response = httpx.get(
                    f"{WG_UPSTREAM}/api/client",
                    timeout=5,
                    auth=auth,
                )
                response.raise_for_status()
                data = response.json()
                for i in data:
                    if i.get("name") == self.user_name:
                        self.wg_data = i
                        break
        except (httpx.HTTPError, json.JSONDecodeError):
            self.wg_data = {}
        finally:
            self.wg_enabled = len(self.wg_data) > 0

    def _fetch_hs_data(self):
        try:
            self.hs_data = {}
            if IS_HS_ENABLED:
                headers = {
                    "Authorization": f"Bearer {APP_HS_API_KEY}",
                }
                user_response = httpx.get(
                    f"{HS_UPSTREAM}/api/v1/user?name={self.user_name}",
                    timeout=3,
                    headers=headers,
                )
                user_response.raise_for_status()
                users = user_response.json().get("users", [])
                logging.info(f"Headscale: got users: {users}")
                if len(users) > 0:
                    user_id = int(users[0].get("id", 0))
                    response = httpx.get(
                        f"{HS_UPSTREAM}/api/v1/preauthkey?user={user_id}",
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

        # Client is registered with wireguard (handled internally)
        if self.wg_enabled:
            rules.insert(
                5,
                {
                    "ip_cidr": ["10.8.0.0/24", "fdcc:ad94:bacf:61a4::cafe:0/112"],
                    "outbound": "wg",
                },
            )
        if self.hs_enabled:
            rules.insert(
                5,
                {
                    "ip_cidr": ["100.64.0.0/24"],
                    "outbound": "ts",
                },
            )

    def __inject_outbounds__(self) -> None:
        outbounds: List[Dict[str, Any]] = [{"type": "direct", "tag": "direct"}]
        outbound_names: list[str] = ["direct"]

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

        now = f"rv-{year}{month:02d}{day:02d}"
        version = now + "-hs" if self.hs_enabled else now

        # Pullup outbounds
        outbounds.append({
            "type": "urltest",
            "tag": version,
            "outbounds": outbound_names,
            "url": "https://www.gstatic.com/generate_204",
            "interval": "30s",
            "tolerance": 100,
        })

        # Eco outbounds
        outbounds.append({
            "type": "urltest",
            "tag": "Eco-Out",
            "outbounds": [i for i in outbound_names if i != "direct"],
            "url": f"https://{self.app_config_host}/generate_204?j={self.user_name}&k={self.user_psk}&expensive=false",
            "interval": "30s",
            "tolerance": 100,
        })

        # Full outbounds
        outbounds.append({
            "type": "selector",
            "tag": "Full-Out",
            "outbounds": [i for i in outbound_names if i != "direct"],
            "default": outbound_names[1] if len(outbound_names) > 1 else "direct",
        })

        self.remote_data["outbounds"] = outbounds

    def __inject_log__(self) -> None:
        log_level = self.log_level or self.remote_data["log"]["level"]
        self.remote_data["log"]["level"] = log_level

    def __inject_endpoints__(self) -> None:
        endpoints: list[dict[str, Any]] = []
        if self.wg_enabled:
            endpoint = WireguardConfig.copy()
            endpoint["address"] = [
                self.wg_data.get("ipv4Address", "10.8.0.0") + "/24",
                self.wg_data.get("ipv6Address", "fdcc:ad94:bacf:61a4::cafe:0") + "/112",
            ]
            endpoint["private_key"] = self.wg_data.get("privateKey", "")
            endpoint["peers"][0]["address"] = self.__server_ip
            endpoint["peers"][0]["port"] = END_PORT + 1
            endpoint["peers"][0]["public_key"] = APP_WG_PUBLIC_KEY
            endpoint["peers"][0]["pre_shared_key"] = self.wg_data.get(
                "preSharedKey", ""
            )
            endpoints.append(endpoint)
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
