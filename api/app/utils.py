import os
import json
import requests

LOCAL_JSON_PATH: str = os.getenv("LOCAL_JSON_PATH", "outs.json")
REMOTE_JSON_URL: str = os.getenv("REMOTE_JSON_URL", "https://raw.githubusercontent.com/minlaxz/nekohasekai/refs/heads/main/api/sing-box-template")
CONFIG_DOMAIN: str = os.getenv("CONFIG_DOMAIN", "www.gstatic.com")


class Loader:
    def __init__(
        self,
        platform,
        version,
        dns_path,
        dns_detour,
        dns_final,
        dns_resolver,
        log_level,
        route_detour,
        user_name,
        user_psk,
    ) -> None:
        self.local_path = LOCAL_JSON_PATH
        self.remote_url = REMOTE_JSON_URL
        self.config_domain = CONFIG_DOMAIN
        self.platform = platform
        self.version = version
        self.dns_path = dns_path
        self.dns_detour = dns_detour
        self.dns_final = dns_final
        self.dns_resolver = dns_resolver
        self.log_level = log_level
        self.route_detour = route_detour
        self.user_name = user_name
        self.user_psk = user_psk
        try:
            with open(self.local_path, "r", encoding="utf-8") as file:
                self.local_data = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError):
            self.local_data = {}

        try:
            if self.remote_url.startswith("https://"):
                response = requests.get(self.remote_url, timeout=5)
                response.raise_for_status()
                self.remote_data = response.json()
            else:
                with open(self.remote_url, "r", encoding="utf-8") as file:
                    self.remote_data = json.load(file)
        except (requests.RequestException, json.JSONDecodeError):
            self.remote_data = {}

    def __inject_dns__(self) -> None:
        self.remote_data["dns"]["final"] = self.dns_final
        if self.platform == "i" and self.version == 11:
            # fmt: off
            self.remote_data["dns"]["servers"] = [
                {
                    "tag": "dns-remote",
                    "address": f"https://dns.nextdns.io{self.dns_path}",
                    "address_resolver": "dns-resolver",
                    "address_strategy": "ipv4_only",
                    "detour": self.dns_detour
                },
                {
                    "tag": "dns-resolver",
                    "address": self.dns_resolver,
                    "detour": self.dns_detour
                },
                {
                    "tag": "dns-local",
                    "address": "local"
                }
            ]
        else:
            # fmt: off
            self.remote_data["dns"]["servers"] = [
                {
                    "tag": "dns-remote",
                    "type": "https",
                    "server": "dns.nextdns.io",
                    "path": self.dns_path,
                    "domain_resolver": "dns-resolver",
                    "detour": self.dns_detour
                },
                {
                    "tag": "dns-resolver",
                    "type": "udp",
                    "server": self.dns_resolver,
                    "detour": self.dns_detour
                },
                {
                    "tag": "dns-local",
                    "type": "local"
                }
            ]
            self.remote_data["route"]["default_domain_resolver"] = {
                "server": "dns-resolver",
                "rewrite_ttl": 60,
                "client_subnet": "1.1.1.1"
            }

    def __inject_outbounds__(self) -> None:
        outbounds: list[dict[str, str | int | list[str]]] = [
            {"type": "direct", "tag": "direct"}
        ]
        outbound_names = ["direct"]
        for i in self.local_data:
            if i.get("tag") == "shadowsocks":
                i["server_port"] = i["server_port"] + 1
                i["password"] = self.user_psk
            outbounds.append(i)
            outbound_names.append(i.get("tag", "unknown"))
            outbounds.append({
                "type": "urltest",
                "tag": "Pullup",
                "outbounds": outbound_names,
                "url": "https://www.gstatic.com/generate_204",
                "interval": "30s",
                "tolerance": 100,
            })
            outbounds.append({
                "type": "urltest",
                "tag": "Ruled",
                "outbounds": outbound_names[1:],  # exclude `direct`
                "url": f"https://{CONFIG_DOMAIN}/generate_204?j={self.user_name}&k={self.user_psk}",
                "interval": "30s",
                "tolerance": 100,
            })
        self.remote_data["outbounds"] = outbounds

    def unwarp(self) -> dict[str, str]:
        self.__inject_dns__()
        self.__inject_outbounds__()
        return self.remote_data


class Checker:
    def __init__(self) -> None:
        pass

    def verify_key(self, k: str) -> bool:
        SSM_API = f"https://{CONFIG_DOMAIN}/api/verify?k={k}"
        try:
            response = requests.get(SSM_API, timeout=5)
            response.raise_for_status()
            data = response.json()
            if data.get("psk") == k:
                return True
            else:
                return False
        except (requests.RequestException, json.JSONDecodeError):
            return False
