import http.server
import json
import urllib.request
import urllib.parse
import os
import redis
import time

LOCAL_JSON_PATH = os.getenv("LOCAL_JSON_PATH", "/data/local.json")
REMOTE_JSON_URL = os.getenv(
    "REMOTE_JSON_URL",
    "https://raw.githubusercontent.com/minlaxz/nekohasekai/refs/heads/main/singbox/v2/sing-box-template",
)
URL_TEST = os.getenv("URL_TEST", "")

r = redis.Redis(host="redis", port=6379, db=0)


class Handler(http.server.BaseHTTPRequestHandler):
    def _handle_check(self, query):
        """Handles /check endpoint for both GET and HEAD methods."""
        self.__dns_path = query.get("dp", [""])[0]  # dp
        user_id = self.__dns_path.split("/")[1] if "/" in self.__dns_path else "unknown"

        client_ip, client_port = self.client_address
        real_ip = self.headers.get("X-Forwarded-For", client_ip)
        ip_key = f"client:{real_ip}"
        now = time.time()

        # --- duplicate detection ---
        last_check = r.get(ip_key)
        is_duplicate = False
        if last_check:
            last_time = float(last_check)  # type: ignore
            if now - last_time < 30:
                is_duplicate = True

        r.set(ip_key, now, ex=60)  # keep timestamp for 60s

        # --- log + store in Redis ---
        if is_duplicate:
            print(f"[DUPLICATE] IP {real_ip} (User {user_id}) checked again too soon.")
            r.incr(f"dup_count:{real_ip}")
        else:
            print(f"Check from {real_ip} (User {user_id})")

        data = {
            "ip": client_ip,
            "port": client_port,
            "real_ip": real_ip,
        }
        r.hset(f"user:{user_id}", mapping=data)
        r.hset(f"user:{user_id}", "last_check", now)  # type: ignore

        # --- send 204 No Content ---
        self.send_response(204)
        self.end_headers()
        return

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
            "- p: platform: android, ios, or empty for mac, linux, windows\n"
            "- v: version: 11 for sing-box 1.11+, 12 for sing-box 1.12+, or empty for 12\n"
            "- dp: dns-path: your private NextDNS profile (optional)\n"
            "- dd: dns-detour: specify any from outbound list, direct will be used if empty\n"
            "- df: dns-final: specify any from dns server list, dns-remote will be used if empty\n"
            "- rdr: remote-dns-detour: local or DNS IP, 1.1.1.1 will be used if empty\n"
            "- mo: modes: specify any from outbound tags, separated by tac, -\n"
            "- rd: route-detour: specify any from outbound list, direct will be used if empty\n"
            "- ll: log-level: specify any from docs, warn will be used if empty\n"
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
                            # https://sing-box.sagernet.org/configuration/shared/udp-over-tcp/#application-support
                            if self.__version.startswith("11"):
                                if self.__platform in ["i"]:
                                    if i.get("tag") == "shadowsocks":
                                        i["udp_over_tcp"]["version"] = 1
                                    if i.get("tag") == "xtls-reality":
                                        i.pop("packet_encoding")
                            if self.__personal_uuid:
                                i["uuid"] = self.__personal_uuid
                            replaced.append(i)
                case "<OTHER_REPLACE>":
                    # fmt: off
                    replaced.append({
                        "type": "urltest",
                        "tag": "Pullup",
                        "outbounds": self.__outbounds,
                        "url": "https://www.gstatic.com/generate_204",
                        "interval": "30s",
                        "tolerance": 100
                    })
                    replaced.append({
                        "type": "urltest",
                        "tag": "Ruled",
                        "outbounds": self.__outbounds[1:] if len(self.__outbounds) > 1 else self.__outbounds,
                        "url": f"{URL_TEST}?dp={self.__dns_path}",
                        "interval": "30s",
                        "tolerance": 100
                    })
                    # ? Could be removed
                    replaced.append({
                        "type": "selector",
                        "tag": "Un-Ruled",
                        "outbounds": self.__outbounds[0:1],
                        "default": self.__outbounds[0]
                    })
                    # fmt: on
                case _:
                    # ? clinet side `direct` outbound
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

    def do_HEAD(self):
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        path = parsed.path

        if path == "/check":
            self._handle_check(query)
        else:
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        path = parsed.path

        if path not in ("/c", "/h", "/tinini", "/check"):
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Sorry, Not Found")
            return

        if path == "/check":
            self._handle_check(query)
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
        # /c?p=a&dp=YOUR_PATH&mo=ss-xr&dd=d
        # /c?p=i&dp=YOUR_PATH&mo=ss-xr&dd=d
        self.mapping = {
            "ss": "shadowsocks",
            "xr": "xtls-reality",
            "d": "direct",
            "l": "local",
        }

        # fmt: off
        self.__platform: str = query.get("p", [""])[0]  # p
        self.__version: str = query.get("v", ["12"])[0] # v
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

        # modes = query.get("mo", [""])[0].split("-")
        # self.__modes = [
        #     self.mapping.get(i, i) for i in modes if i
        # ]  # mo
        self.__modes = ["shadowsocks", "xtls-reality"]

        self.__personal_uuid = query.get("puuid", [""])[0]  # puuid

        self.__ts_auth_key = query.get("tak", [""])[0]  # tak
        self.__ts_exit_node = query.get("ten", [""])[0]  # ten
        self.__ts_hostname = query.get("th", [""])[0] or "ts-sb"  # th

        # self.__ipv6_only: bool = query.get("ipv6-only", ["false"])[0] == "true"
        # self__enable_ipv6: bool = query.get("enable-ipv6", ["false"])[0] == "true"

        self.__load()
        self.__inject_dns()
        self.__inject_outbounds()
        self.__inject_others()
        if self.__platform in ["a", "i"]:
            self.remote_data["route"]["override_android_vpn"] = True

        body = json.dumps(self.remote_data, indent=2).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    port = int(os.getenv("CONFIG_SERVER_PORT", 8851))
    print(f"Starting config server on port {port}...")
    http.server.HTTPServer(("0.0.0.0", port), Handler).serve_forever()
