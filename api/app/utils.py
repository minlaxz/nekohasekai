from typing import Dict, Any

import os
import json
import httpx
import datetime

LOCAL_JSON_PATH: str = os.getenv("LOCAL_JSON_PATH", "outs.json")
REMOTE_JSON_URL: str = os.getenv("REMOTE_JSON_URL", "sing-box-template")

CONFIG_HOST: str = os.getenv("CONFIG_HOST", "www.gstatic.com")
START_PORT: int = int(os.getenv("START_PORT", "8040"))
END_PORT: int = int(os.getenv("END_PORT", "8050"))

SSM_SERVER: str = os.getenv("SSM_SERVER", "localhost")
SSM_UPSTREAM = f"http://{SSM_SERVER}:{END_PORT}"

WG_SERVER: str = os.environ.get("WG_SERVER", "wg-easy")
WG_SERVER_PORT: str = os.environ.get("WG_SERVER_PORT", "51821")
WG_PUBLIC_KEY: str = os.getenv("WG_PUBLIC_KEY", "")
WG_SERVER_USERNAME: str = os.getenv("WG_SERVER_USERNAME", "")
WG_SERVER_PASSWORD: str = os.getenv("WG_SERVER_PASSWORD", "")
WG_UPSTREAM = f"http://{WG_SERVER}:{WG_SERVER_PORT}"
IS_WG_ENABLED = all([WG_SERVER_USERNAME, WG_SERVER_PASSWORD, WG_PUBLIC_KEY])

day = datetime.datetime.now(datetime.timezone.utc).day
month = datetime.datetime.now(datetime.timezone.utc).month
year = datetime.datetime.now(datetime.timezone.utc).year

EndpointConfig: Dict[str, Any] = {
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
        wg: int,
        please: bool = False,
    ) -> None:
        self.local_path = LOCAL_JSON_PATH
        self.remote_url = REMOTE_JSON_URL
        self.config_host = CONFIG_HOST
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
        self.wg = wg
        try:
            with open(self.local_path, "r", encoding="utf-8") as file:
                self.local_data: Dict[str, Any] = json.load(file)
                self.__server_ip: str = self.local_data.get("outbounds", [])[0].get(
                    "server", ""
                )
        except (FileNotFoundError, json.JSONDecodeError):
            self.local_data = {}

        try:
            if self.remote_url.startswith("https://"):
                response = httpx.get(
                    self.remote_url + f"-v{self.version}"
                    if self.version == 11
                    else self.remote_url,
                    timeout=5,
                )
                response.raise_for_status()
                self.remote_data: Dict[str, Any] = response.json()
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

        try:
            self.wg_data: Dict[str, Any] = {}
            if IS_WG_ENABLED:
                auth = httpx.BasicAuth(
                    username=WG_SERVER_USERNAME, password=WG_SERVER_PASSWORD
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

    def __inject_dns__(self) -> None:
        # Default: `dns-final` otherwise client provided
        # Values: dns-remote, dns-resolver, [dns-final]
        dns_final = self.dns_final or self.remote_data["dns"]["final"]
        self.remote_data["dns"]["final"] = dns_final

        # Assuming DNS_PATH ends with a trailing slash
        # e.g., /user_name
        # e.g., /custom_path/user_name
        dns_path = self.dns_path + self.user_name
        if self.version == 11:
            # Version 11
            for i in self.remote_data["dns"]["servers"]:
                match i.get("tag"):
                    case "dns-remote":
                        i["address"] = f"https://{self.dns_host}{dns_path}"
                    case "dns-resolver":
                        i["address"] = self.dns_resolver
                        # Client provided `dns_detour` i.e: `dd` for dns-resolver
                        i["detour"] = self.dns_detour or i.get("detour")
                    case _:
                        # Skip others
                        pass
        else:
            # Version 12+
            for i in self.remote_data["dns"]["servers"]:
                match i.get("tag"):
                    case "dns-remote":
                        i["server"] = self.dns_host
                        i["path"] = dns_path
                    case "dns-resolver":
                        i["server"] = self.dns_resolver
                        # Client provided `dns_detour` i.e: `dd` for dns-resolver
                        i["detour"] = self.dns_detour or i.get("detour")
                    case _:
                        # Skip others
                        pass

    def __inject_routes__(self) -> None:
        # Client provided `route_detour` i.e: `rd` for route download detour
        for i in self.remote_data["route"]["rule_set"]:
            i["download_detour"] = self.route_detour or i.get("download_detour")

        # fmt: off
        if len(self.wg_data) > 0:
            self.remote_data["route"]["rules"].insert(5, {
                "ip_cidr": ["10.8.0.0/24", "fdcc:ad94:bacf:61a4::cafe:0/112"],
                "ip_version": 6,
                "outbound": "wg"
            })

    def __inject_outbounds__(self) -> None:
        # fmt: off
        outbounds: list[dict[str, str | int | list[str]]] = [
            {"type": "direct", "tag": "direct"}
        ]
        outbound_names: list[str] = ["direct"]
        # fmt: on

        for i in self.local_data["outbounds"]:
            if i.get("tag") == "shadowsocks":
                # ! Overwrite psk for shadowsocks outbound if quota exceeded
                upsk = "invalid_psk_overwritten" if self.disabled else self.user_psk
                i["password"] = upsk

            # ! Remove multiplex from all outbounds if requested i.e. ?mx=false
            if not self.multiplex:
                _ = i.pop("multiplex", None):

            # * Append other outbounds, e.g., trojan, vless, etc.
            outbounds.append(i)
            outbound_names.append(i.get("tag"))

        # fmt: off
        # Pullup outbounds
        outbounds.append({
            "type": "urltest",
            "tag": f"rv-{year}{month:02d}{day:02d}",
            "outbounds": outbound_names + ["wg"] if len(self.wg_data) > 0 else outbound_names,
            "url": "https://www.gstatic.com/generate_204",
            "interval": "30s",
            "tolerance": 100
        })

        # Ruled outbounds
        outbounds.append({
            "type": "urltest",
            "tag": "Eco-Out",
            "outbounds": outbound_names[1:],  # exclude `direct`
            "url": f"https://{self.config_host}/generate_204?j={self.user_name}&k={self.user_psk}&expensive=false",
            "interval": "30s",
            "tolerance": 100
        })
        outbounds.append({
            "type": "selector",
            "tag": "Full-Out",
            "outbounds": outbound_names[1:],  # exclude `direct`
            "default": outbound_names[1] # Assuming there're two outbounds at least
        })

        self.remote_data["outbounds"] = outbounds

    def __inject_log__(self) -> None:
        log_level = self.log_level or self.remote_data["log"]["level"]
        self.remote_data["log"]["level"] = log_level

    def __inject_endpoints__(self) -> None:
        endpoints: list[dict[str, Any]] = []
        if len(self.wg_data) > 0:
            endpoint = EndpointConfig.copy()
            endpoint["address"] = [
                self.wg_data.get("ipv4Address", "10.8.0.0") + "/24",
                self.wg_data.get("ipv6Address", "fdcc:ad94:bacf:61a4::cafe:0") + "/112",
            ]
            endpoint["private_key"] = self.wg_data.get("privateKey", "")
            endpoint["peers"][0]["address"] = self.__server_ip
            endpoint["peers"][0]["port"] = END_PORT + 1
            endpoint["peers"][0]["public_key"] = WG_PUBLIC_KEY
            endpoint["peers"][0]["pre_shared_key"] = self.wg_data.get(
                "preSharedKey", ""
            )
            endpoints.append(endpoint)
        self.remote_data["endpoints"] = endpoints

    def unwarp(self, disabled: bool = False) -> Dict[str, Any]:
        self.disabled: bool = disabled
        self.__inject_dns__()
        self.__inject_log__()
        self.__inject_outbounds__()
        self.__inject_endpoints__()
        self.__inject_routes__()
        return self.remote_data


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
