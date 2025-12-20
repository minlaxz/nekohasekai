from typing import Dict, Any

import os
import json
import httpx

LOCAL_JSON_PATH: str = os.getenv("LOCAL_JSON_PATH", "outs.json")
REMOTE_JSON_URL: str = os.getenv("REMOTE_JSON_URL", "sing-box-template")

CONFIG_HOST: str = os.getenv("CONFIG_HOST", "www.gstatic.com")
START_PORT: int = int(os.getenv("START_PORT", "8040"))
END_PORT: int = int(os.getenv("END_PORT", "8050"))

SSM_SERVER: str = os.getenv("SSM_SERVER", "localhost")
SSM_UPSTREAM = f"http://{SSM_SERVER}:{END_PORT}"


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

        # Experimental WireGuard routing rule injection, wg can be 2-253
        # * #0 subnet, #1 server, #255 broadcast, #254 is reserved
        if self.wg > 1 and self.wg < 254:
            # fmt: off
            self.remote_data["route"]["rules"].append(
                {
                    "type": "logical",
                    "mode": "or",
                    "rules": [{"ip_cidr": [f"10.10.10.{self.wg}/24"]}],
                    "action": "route",
                    "outbound": "wg-ep-sb"
                }
            )
        # fmt: on
        if os.getenv("WARP_ENABLED", "false").lower() == "true":
            # Inject WARP routing rule
            # 0 to 3 is reserved by inbounds rules, 4 is reserved by dns rules
            # fmt: off
            self.remote_data["route"]["rules"].insert(5,
                {
                    "type": "logical",
                    "mode": "or",
                    "rules": [
                        {
                            "rule_set": [
                                "geosite-cloudflare",
                                "geoip-cloudflare"
                            ]
                        },
                        {
                            "ip_cidr": [
                                os.getenv("INTERFACE_ADDRESS4", "").split("/")[0] + "/24",
                                os.getenv("INTERFACE_ADDRESS6", "").split("/")[0] + "/124"
                            ]
                        },
                        {
                            "ip_version": 6
                        }
                    ],
                    "action": "route",
                    "outbound": "wgep-cloud"
                }
            )

    def __inject_outbounds__(self) -> None:
        # fmt: off
        outbounds: list[dict[str, str | int | list[str]]] = [
            {"type": "direct", "tag": "direct"}
        ]
        outbound_names: list["str"] = ["direct"]
        if os.getenv("WARP_ENABLED", "false").lower() == "true":
            outbound_names.append("wgep-cloud")
        # fmt: on

        for i in self.local_data["outbounds"]:
            if i.get("tag") == "shadowsocks":
                # ! Overwrite psk for shadowsocks outbound if quota exceeded
                upsk = "invalid_psk_overwritten" if self.disabled else self.user_psk
                i["password"] = upsk

            # ! Remove multiplex from all outbounds if requested i.e. ?mx=false
            if not self.multiplex:
                del i["multiplex"]

            # * Append other outbounds, e.g., trojan, vless, etc.
            outbounds.append(i)
            outbound_names.append(i.get("tag"))

        # fmt: off
        # Pullup outbounds
        outbounds.append({
            "type": "urltest",
            "tag": "Pullup",
            "outbounds": outbound_names,
            "url": "https://www.gstatic.com/generate_204",
            "interval": "30s",
            "tolerance": 100
        })

        # Ruled outbounds
        outbounds.append({
            "type": "urltest",
            "tag": "Novice-Out",
            "outbounds": outbound_names[1:],  # exclude `direct`
            "url": f"https://{self.config_host}/generate_204?j={self.user_name}&k={self.user_psk}&expensive=false",
            "interval": "30s",
            "tolerance": 100
        })
        outbounds.append({
            "type": "selector",
            "tag": "Expensive-Out",
            "outbounds": outbound_names[1:],  # exclude `direct`
            "default": outbound_names[1] # Assuming there're two outbounds at least
        })

        self.remote_data["outbounds"] = outbounds

    def __inject_log__(self) -> None:
        log_level = self.log_level or self.remote_data["log"]["level"]
        self.remote_data["log"]["level"] = log_level

    def __inject_endpoints__(self) -> None:
        endpoints: list[dict[str, Any]] = []
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
