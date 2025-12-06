from typing import Dict, Any

import os
import json
import httpx

LOCAL_JSON_PATH: str = os.getenv("LOCAL_JSON_PATH", "outs.json")
REMOTE_JSON_URL: str = os.getenv("REMOTE_JSON_URL", "sing-box-template")
CONFIG_SERVER: str = os.getenv("CONFIG_SERVER", "www.gstatic.com")
START_PORT: int = int(os.getenv("START_PORT", "1080"))
SSM_SERVER: str = os.getenv("SSM_SERVER", "localhost")
SSM_PORT: int = START_PORT + 10
SSM_UPSTREAM = f"http://{SSM_SERVER}:{SSM_PORT}"
DNS_PATH: str = os.getenv("DNS_PATH", "/")


class Loader:
    def __init__(
        self,
        platform: str,
        version: int,
        dns_path: str,
        dns_detour: str,
        dns_final: str,
        dns_resolver: str,
        log_level: str,
        route_detour: str,
        route_final: str,
        username: str,
        psk: str,
        wg: int,
        please: bool = False,
    ) -> None:
        self.local_path = LOCAL_JSON_PATH
        self.remote_url = REMOTE_JSON_URL
        self.config_server = CONFIG_SERVER
        self.platform = platform
        self.version = version
        self.dns_path = dns_path
        self.dns_detour = dns_detour
        self.dns_final = dns_final
        self.dns_resolver = dns_resolver
        self.log_level = log_level
        self.route_detour = route_detour
        self.route_final = route_final
        self.user_name = username
        self.user_psk = psk
        self.wg = wg
        self.please = please
        try:
            with open(self.local_path, "r", encoding="utf-8") as file:
                self.local_data: Dict[str, Any] = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError):
            self.local_data = {}

        try:
            if self.remote_url.startswith("https://"):
                response = httpx.get(self.remote_url, timeout=5)
                response.raise_for_status()
                self.remote_data: Dict[str, Any] = response.json()
            else:
                with open(self.remote_url, "r", encoding="utf-8") as file:
                    self.remote_data = json.load(file)
        except (httpx.HTTPError, json.JSONDecodeError):
            self.remote_data = {}

    def __inject_dns__(self) -> None:
        # client defined dns_path otherwise server defined dns_path
        dns_path = (
            self.dns_path if self.dns_path != "/" else DNS_PATH + f"{self.user_name}"
        )
        self.remote_data["dns"]["final"] = self.dns_final
        if self.platform == "i" and self.version == 11:
            # fmt: off
            for i in self.remote_data["dns"]["servers"]:
                match i.get("tag"):
                    case "dns-remote":
                        # Version 11 does not support these fields
                        i.pop("type", None)
                        i.pop("server", None)
                        i.pop("path", None)
                        i.pop("domain_resolver", None)
                        i["address"] = f"https://dns.nextdns.io{dns_path}"
                        i["address_resolver"] = "dns-resolver"
                        i["address_strategy"] = "ipv4_only"
                    case "dns-resolver":
                        # Version 11 does not support these fields
                        i.pop("type", None)
                        i.pop("server", None)
                        i["address"] = self.dns_resolver
                    case "dns-local":
                        i["address"] = "local"
                        # Version 11 does not support these fields
                        i.pop("type", None)
                    case _:
                        # Skip others
                        pass
        else:
            # Other combinations but custom `dns_path` is provided
            self.remote_data["dns"]["servers"][0]["path"] = dns_path

        # Client provided `dns_detour`, excluding `dns-remote` check in template
        for i in self.remote_data["dns"]["servers"]:
            if i.get("tag") != "dns-remote":
                i["detour"] = self.dns_detour

    def __inject_routes__(self) -> None:
        if self.platform == "i" and self.version == 11:
            # Version 11 does not support these fields
            self.remote_data["route"].pop("default_domain_resolver", None)
        else:
            # Skip others
            pass

        if self.wg:
            # fmt: off
            self.remote_data["route"]["rules"].append(
                {
                    "type": "logical",
                    "mode": "or",
                    "rules": [{"ip_cidr": ["10.10.10.0/24"]}],
                    "action": "route",
                    "outbound": "wg-ep-sb"
                }
            )

        # Client provided `route_detour`
        for i in self.remote_data["route"]["rule_set"]:
            i["download_detour"] = self.route_detour

        # Expensive operation: Client provided `route_final` as final outbound
        self.remote_data["route"]["final"] = self.route_final

    def __inject_outbounds__(self) -> None:
        # fmt: off
        outbounds: list[dict[str, str | int | list[str]]] = [
            {"type": "direct", "tag": "direct"}
        ]
        outbound_names = ["direct"]

        # TODO: Refactor this mess from generator side.
        for i in self.local_data["outbounds"]:
            if i.get("tag") == "shadowsocks":
                i["password"] = "invalid_psk_overwritten" if self.disabled else self.user_psk

            # All other outbounds are added as-is.
            if i.get("tag") != "ssm-api":
                outbounds.append(i)
                outbound_names.append(i.get("tag", "unknown"))

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
            "tag": "Ruled",
            "outbounds": outbound_names[1:],  # exclude `direct`
            "url": f"https://{self.config_server}/generate_204?j={self.user_name}&k={self.user_psk}&expensive=false",
            "interval": "30s",
            "tolerance": 100
        })
        outbounds.append({
            "type": "urltest",
            "tag": "Ruled-Expensive",
            "outbounds": outbound_names[1:],  # exclude `direct`
            "url": f"https://{self.config_server}/generate_204?j={self.user_name}&k={self.user_psk}&expensive=true",
            "interval": "30s",
            "tolerance": 100
        })

        self.remote_data["outbounds"] = outbounds

    def __inject_log__(self) -> None:
        self.remote_data["log"]["level"] = self.log_level

    def __inject_endpoints__(self) -> None:
        if not self.wg:
            del self.remote_data["endpoints"]
        else:
            endpoint = self.remote_data["endpoints"][0]
            peers = endpoint.get("peers", [])
            # Keys are always stored in the last outbound
            wg_keys = self.local_data["outbounds"][-1]["keys"]

            endpoint["address"] = [wg_keys[f"wg_address_{self.wg}"]]
            endpoint["private_key"] = wg_keys[f"wg_priv_{self.wg}"]
            for peer in peers:
                peer["address"] = wg_keys["wg_address_0"]
                peer["port"] = START_PORT + 2
                peer["public_key"] = wg_keys["wg_pub_0"]

    def unwarp(self, disabled: bool = False) -> Dict[str, Any]:
        self.disabled: bool = disabled
        self.__inject_dns__()
        self.__inject_log__()
        self.__inject_routes__()
        self.__inject_outbounds__()
        self.__inject_endpoints__()
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
            > 10_000_000_000
        )  # 10 GB Limits or not pleasing :3

    def unwarp(self, disabled: bool = False) -> Dict[str, Any]:
        return super().unwarp(disabled=self.is_quota_limited())
