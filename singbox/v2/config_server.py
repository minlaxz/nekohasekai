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
CONFIG_DOMAIN = os.getenv("CONFIG_DOMAIN", "")

r = redis.Redis(host="redis", port=6379, db=0)


class Handler(http.server.BaseHTTPRequestHandler):
    def _handle_check(self, query):
        """Handles /check endpoint for both GET and HEAD methods."""
        # TODO To check j and k with ssm-api for abuse usage
        # If j is not found in ssm database, k will be removed from users list.
        user_id = self.__ss_user if self.__ss_user else "unknown"

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
            "Usage: /c?p=i&v=11\n"
            "Parameters:\n"
            "- p: platform:\n"
            "android, ios, mac, linux, windows or empty for android\n"
            "- v: version:\n"
            "11 for sing-box 1.11+, 12 for sing-box 1.12+, or empty for 12\n"
            "- dp: dns-path:\n"
            "private NextDNS profile, or / by default\n"
            "- dd: dns-detour:\n"
            "any from outbounds, direct for 1.11+ or outbounds[0] for 1.12+ by default\n"
            "- df: dns-final:\n"
            "any from dns.servers, 'dns-remote' by deafult\n"
            "- rdr: remote-dns-detour:\n"
            "local or DNS IP, 1.1.1.1 by default\n"
            "- rd: route-detour:\n"
            "any from outbound list, direct by deafult\n"
            "- ll: log-level:\n"
            "trace, default, info, warn, error, critical, warn by default\n"
            "- tak: tailscale auth key:\n"
            "Tailscale ephemeral auth key, skip by default\n"
            "- ten: tailscale exit node\n"
            "Tailscale exit node IP, skip by default\n"
            "- th: tailscale host name:\n"
            "Tailscale hostname, skip by default, ts-sb if tak and ten exists\n"
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
                    "address": f"https://dns.nextdns.io{self.__dns_path}",
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
                    "path": self.__dns_path,
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
        # Next plan
        # WIFI -> dns-direct --> dns-remote
        # MOBILE -> dns-local --> dns-remote

    def __inject_outbounds(self):
        outbounds = []
        for item in self.remote_data.get("outbounds", []):
            match item:
                case "<OUTBOUND_REPLACE>":
                    for i in self.local_data:
                        if i.get("tag") == "shadowsocks":
                            if self.__ss_password:
                                i["server_port"] = i["server_port"] + 1
                                i["password"] = self.__ss_password
                            outbounds.append(i)
                case "<OTHER_REPLACE>":
                    # fmt: off
                    outbounds.append({
                        "type": "urltest",
                        "tag": "Pullup",
                        "outbounds": self.__outbounds,
                        "url": "https://www.gstatic.com/generate_204",
                        "interval": "30s",
                        "tolerance": 100
                    })
                    outbounds.append({
                        "type": "urltest",
                        "tag": "Ruled",
                        "outbounds": self.__outbounds[1:],  # exclude direct
                        "url": f"https://{CONFIG_DOMAIN}/check?j={self.__ss_user}&k={self.__ss_password}",
                        "interval": "30s",
                        "tolerance": 100
                    })
                    # fmt: on
                case _:
                    # ? clinet side `direct` outbound
                    outbounds.append(item)
        self.remote_data["outbounds"] = outbounds

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

        if path not in ("/c", "/h", "/check"):
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
        self.__platform: str = query.get("p", ["a"])[0]  # p
        self.__version: str = query.get("v", ["12"])[0] # v
        self.__dns_path = query.get("dp", ["/"])[0]  # dp
        self.__dns_final = query.get("df", ["dns-remote"])[0]  # df
        self.__dns_detour = query.get("dd", ["direct"])[0]  # dd
        self.__remote_dns_resolver = query.get("rdr", ["1.1.1.1"])[0]  # rdr
        self.__route_detour = query.get("rd", ["direct"])[0]  # rd
        self.__log_level = query.get("ll", ["warn"])[0]  # ll

        self.__ss_user = query.get("j", [""])[0]  # shadowsocks custom user
        self.__ss_password = query.get("k", [""])[0]  # shadowsocks custom password

        self.__ts_auth_key = query.get("tak", [""])[0]  # tak
        self.__ts_exit_node = query.get("ten", [""])[0]  # ten
        self.__ts_hostname = query.get("th", ["ts-sb"])[0]  # th

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
