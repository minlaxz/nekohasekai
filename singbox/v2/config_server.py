import http.server
import json
import urllib.request
import urllib.parse
import os

LOCAL_JSON_PATH = os.getenv("LOCAL_JSON_PATH", "/data/local.json")
REMOTE_JSON_URL = os.getenv(
    "REMOTE_JSON_URL",
    "https://raw.githubusercontent.com/minlaxz/nekohasekai/refs/heads/main/singbox/v2/sing-box-template",
)


class Handler(http.server.BaseHTTPRequestHandler):
    def __load(self):
        try:
            with open(LOCAL_JSON_PATH) as f:
                self.local_data = json.load(f)
            with urllib.request.urlopen(REMOTE_JSON_URL) as r:
                self.remote_data = json.load(r)
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            msg = f"Error: {str(e)}"
            self.wfile.write(msg.encode())

    def __send_help(self):
        help_msg = (
            "Usage: /client.json?platform=android&version=12&nextdns-path=YOUR_PATH\n"
            "Parameters:\n"
            "- p: android, ios, or empty for mac, linux, windows\n"
            "- v: 11 for sing-box 1.11+, 12 for sing-box 1.12+, or empty for 12\n"
            "- dp: your private NextDNS profile (optional)\n"
            "- dd: specify any from outbound list, direct will be used if empty\n"
            "- df: specify any from dns server list, dns-remote will be used if empty\n"
            "- rdr: local or DNS IP, 1.1.1.1 will be used if empty\n"
            "- mo: specify any from outbound tags, separated by &\n"
            "- rd: specify any from outbound list, direct will be used if empty\n"
            "- ll: specify any from docs, warn will be used if empty\n"
            "- tak: your Tailscale ephemeral auth key (optional)\n"
            "- ten: your Tailscale exit node IP (optional)\n"
            "- th: your Tailscale hostname (optional, default: ts-sb)\n"
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(help_msg)))
        self.end_headers()
        self.wfile.write(help_msg.encode())
        return

    def __inject_dns(self):
        if self.__version.startswith("11"):
            # fmt: off
            self.remote_data["dns"]["servers"] = [
                {
                    "tag": "dns-remote",
                    "address": f"https://dns.nextdns.io/{self.__dns_path}"
                    if self.__dns_path
                    else "https://dns.nextdns.io/",
                    "address_resolver": "dns-resolver",
                    "address_strategy": "ipv4_only",
                    "detour": self.__dns_detour
                },
                {
                    "tag": "dns-resolver",
                    "address": self.__remote_dns_resolver,
                    "detour": self.__dns_detour
                }
            ]
        else:
            # fmt: off
            self.remote_data["dns"]["servers"] = [
                {
                    "tag": "dns-remote",
                    "type": "https",
                    "server": "dns.nextdns.io",
                    "path": self.__dns_path if self.__dns_path else "/",
                    "domain_resolver": "dns-resolver",
                    "detour": self.__dns_detour
                }
            ]
            if self.__remote_dns_resolver.lower() == "local":
                self.remote_data["dns"]["servers"].append({
                    "tag": "dns-resolver",
                    "type": "local"
                })
            else:
                self.remote_data["dns"]["servers"].append({
                    "tag": "dns-resolver",
                    "type": "udp",
                    "server": self.__remote_dns_resolver,
                    "detour": self.__dns_detour
                })
            self.remote_data["route"]["default_domain_resolver"] = {
                "server": "dns-resolver",
                "rewrite_ttl": 60,
                "client_subnet": "1.1.1.1"
            }
        self.remote_data["dns"]["final"] = self.__dns_final
        # WIFI -> dns-direct --> dns-remote
        # MOBILE -> dns-local --> dns-remote

    def __inject_outbounds(self):
        replaced = []
        for item in self.remote_data.get("outbounds", []):
            match item:
                case "<OUTBOUND_REPLACE>":
                    for i in self.local_data:
                        if i["tag"] in self.__modes:
                            replaced.append(i)
                case "<PULLUP_REPLACE>":
                    # fmt: off
                    replaced.append({
                        "type": "urltest",
                        "tag": "Pullup",
                        "outbounds": self.__outbounds,
                        "url": "http://www.gstatic.com/generate_204",
                        "interval": "1m",
                        "tolerance": 100
                    })
                    # fmt: on
                case "<REGISTERED_REPLACE>":
                    # fmt: off
                    replaced.append({
                        "type": "selector",
                        "tag": "Registered",
                        "outbounds": self.__outbounds,
                        "default": self.__outbounds[1] if len(self.__outbounds) > 1 else self.__outbounds[0]
                    })
                    # fmt: on
                case "<UNREGISTERED_REPLACE>":
                    # fmt: off
                    replaced.append({
                        "type": "selector",
                        "tag": "Unregistered",
                        "outbounds": self.__outbounds,
                        "default": self.__outbounds[0]
                    })
                    # fmt: on
                case "<OPTIONS_P0RN_REPLACE>":
                    # fmt: off
                    replaced.append({
                        "type": "selector",
                        "tag": "Options P0rn",
                        "outbounds": self.__outbounds,
                        "default": self.__outbounds[0]
                    })
                    # fmt: on
                case _:
                    # `direct` maybe?
                    replaced.append(item)
        self.remote_data["outbounds"] = replaced

    def __inject_others(self):
        if all([
            self.__ts_auth_key,
            self.__ts_exit_node,
            self.__ts_hostname,
        ]) and self.__version.startswith("12"):
            # fmt: off
            self.remote_data["endpoints"] = [
                {
                    "type": "tailscale",
                    "tag": self.__ts_hostname + "-ep",
                    "auth_key": self.__ts_auth_key,
                    "ephemeral": True,
                    "hostname": self.__ts_hostname,
                    "accept_routes": True,
                    "advertise_exit_node": False,
                    "udp_timeout": "5m",
                    "domain_resolver": "dns-remote",
                    "exit_node": self.__ts_exit_node
                }
            ]
            # fmt: on
            for item in self.remote_data["outbounds"]:
                if item.get("type") == "urltest" or item.get("type") == "selector":
                    item["outbounds"].append(self.__ts_hostname + "-ep")
        for i in self.remote_data["route"]["rule_set"]:
            i["download_detour"] = self.__route_detour

        self.remote_data["log"]["level"] = self.__log_level

    @property
    def __outbounds(self):
        _ = ["direct"]
        for i in self.local_data:
            _.append(i.get("tag"))
        return _

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        path = parsed.path

        if path not in ("/c", "/h"):
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Sorry, Not Found")
            return

        if path == "/h":
            self.__send_help()

        # Otherwise
        # self.__query: dict = query
        # self.__path: str = path

        # Mobile Data
        # /c?p=a&dp=YOUR_PATH&rdr=local&mo=ss
        # /cjson?p=i&dp=YOUR_PATH&rdr=local&mo=ss

        # Wi-Fi
        # /c?p=a&dp=YOUR_PATH&mo=ss&dd=d
        # /c?p=i&dp=YOUR_PATH&mo=ss&dd=d
        self.mapping = {"ss": "shadowsocks", "d": "direct", "l": "local"}

        # fmt: off
        self.__platform: list = query.get("p", [""])[0].split("&")  # p
        self.__version: str = "12" if self.__platform != "i" else query.get("v", ["12"])[0] # v
        self.__dns_path = query.get("dp", [""])[0]  # dp
        self.__dns_final = query.get("df", ["dns-remote"])[0]  # df

        __dd__ = query.get("dd", ["d"])[0] # dd
        self.__dns_detour = self.mapping.get(__dd__, __dd__)


        __rdr__ = query.get("rdr", ["1.1.1.1"])[0] # rdr
        self.__remote_dns_resolver = self.mapping.get(__rdr__, __rdr__)

        __rd__ = query.get("rd", ["d"])[0]  # rd
        self.__route_detour = self.mapping.get(__rd__, __rd__)

        __ll__ = query.get("ll", ["warn"])[0]  # ll
        self.__log_level = self.mapping.get(__ll__, __ll__)

        self.__modes = [
            self.mapping.get(i, i) for i in query.get("mo", [""])[0].split("&") if i
        ]  # mo

        self.__ts_auth_key = query.get("tak", [""])[0]  # tak
        self.__ts_exit_node = query.get("ten", [""])[0]  # ten
        self.__ts_hostname = query.get("th", [""])[0] or "ts-sb"  # th

        # self.__ipv6_only: bool = query.get("ipv6-only", ["false"])[0] == "true"
        # self__enable_ipv6: bool = query.get("enable-ipv6", ["false"])[0] == "true"

        self.__load()
        self.__inject_dns()
        self.__inject_outbounds()
        self.__inject_others()
        if "a" in self.__platform or "i" in self.__platform:
            self.remote_data["route"]["override_android_vpn"] = True

        body = json.dumps(self.remote_data, indent=2).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    port = int(os.getenv("CONFIG_SERVER_PORT", 8851))
    http.server.HTTPServer(("0.0.0.0", port), Handler).serve_forever()
