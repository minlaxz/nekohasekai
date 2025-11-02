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


def get_outbounds() -> list[str]:
    outbounds = ["direct"]
    if os.getenv("SHADOWSOCKS") or os.getenv("SHADOWSOCKSX"):
        outbounds.append("shadowsocks")
    if os.getenv("XTLS_REALITY") or os.getenv("XTLS_REALITYX"):
        outbounds.append("xtls-reality")
    return outbounds


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)

        query = urllib.parse.parse_qs(parsed.query)
        path = parsed.path

        # platform=android -> is_android = True
        platform = query.get("platform", [""])[0].split("&")
        is_android = "android" in platform
        is_ios = "ios" in platform

        # version=11 or version=12 -> sing-box version 1.11 or 1.12
        version = query.get("version", ["12"])[0]

        # nextdns-path=YOUR_PATH -> private NextDNS path
        private_nextdns_path = query.get("nextdns-path", [""])[0]

        # Enable Tailscale Endpoint if Tailscale ephemeral auth keys proivded
        ts_auth_key = query.get("ts-auth-key", [""])[0]
        ts_exit_node = query.get("ts-exit-node", [""])[0]
        ts_hostname = query.get("ts-hostname", ["ts-sb"])[0]

        dns_detour = query.get("dns-detour", ["direct"])[0]

        # ipv6-only=1 -> enable ipv6 (not stable yet)
        # is_ipv6 = query.get("ipv6-only", ["0"])[0] == "1"

        if path not in ("/client.json", "/help"):
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Sorry, Not Found")
            return

        if path == "/help":
            help_msg = (
                "Usage: /client.json?platform=android&version=12&nextdns-path=YOUR_PATH\n"
                "Parameters:\n"
                "- platform: android, ios, or empty (for mac, linux, windows)\n"
                "- version: 11 for sing-box 1.11+, 12 for sing-box 1.12+\n"
                "- nextdns-path: your private NextDNS profile (optional)\n"
                "- dns-detour: specify any from outbound list, direct will be used otherwise\n"
                "- ts-auth-key: your Tailscale ephemeral auth key (optional)\n"
                "- ts-exit-node: your Tailscale exit node IP (optional)\n"
                "- ts-hostname: your Tailscale hostname (optional, default: ts-sb)\n"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(help_msg)))
            self.end_headers()
            self.wfile.write(help_msg.encode())
            return

        try:
            with open(LOCAL_JSON_PATH) as f:
                local_data = json.load(f)
            with urllib.request.urlopen(REMOTE_JSON_URL) as r:
                remote_data = json.load(r)

            replaced = []
            for item in remote_data.get("outbounds", []):
                match item:
                    case "<OUTBOUND_REPLACE>":
                        for i in local_data:
                            replaced.append(i)
                    case "<PULLUP_REPLACE>":
                        # fmt: off
                        replaced.append({
                            "type": "urltest",
                            "tag": "Pullup",
                            "outbounds": get_outbounds(),
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
                            "outbounds": get_outbounds(),
                            "default": get_outbounds()[1]
                        })
                        # fmt: on
                    case "<UNREGISTERED_REPLACE>":
                        # fmt: off
                        replaced.append({
                            "type": "selector",
                            "tag": "Unregistered",
                            "outbounds": get_outbounds(),
                            "default": get_outbounds()[0]
                        })
                        # fmt: on
                    case "<OPTIONS_P0RN_REPLACE>":
                        # fmt: off
                        replaced.append({
                            "type": "selector",
                            "tag": "Options P0rn",
                            "outbounds": get_outbounds(),
                            "default": get_outbounds()[0]
                        })
                        # fmt: on
                    case _:
                        # `direct` maybe?
                        replaced.append(item)
            remote_data["outbounds"] = replaced

            if is_android or is_ios:
                remote_data["route"]["override_android_vpn"] = True

            # fmt: off
            if version.startswith("11"):
                remote_data["dns"]["servers"] = [
                    {
                        "tag": "dns-remote",
                        "address": f"https://dns.nextdns.io/{private_nextdns_path}" if private_nextdns_path else "https://dns.nextdns.io/",
                        "address_resolver": "dns-direct",
                        "address_strategy": "ipv4_only",
                        "detour": dns_detour
                    },
                    {
                        "tag": "dns-direct",
                        "address": "1.1.1.1",
                        "detour": dns_detour
                    }
                ]
            else: # default to version 1.12+
                remote_data["dns"]["servers"] = [
                    {
                        "tag": "dns-remote",
                        "type": "https",
                        "server": "dns.nextdns.io",
                        "path": private_nextdns_path if private_nextdns_path else "/",
                        "domain_resolver": "dns-direct",
                        "detour": dns_detour
                    },
                    {
                        "tag": "dns-direct",
                        "type": "udp",
                        "server": "1.1.1.1",
                        "detour": dns_detour
                    }
                ]
                remote_data["route"]["default_domain_resolver"] = {
                    "server": "dns-direct",
                    "rewrite_ttl": 60,
                    "client_subnet": "1.1.1.1"
                }

                # Enable Tailscale Endpoint if auth key and exit node provided, only for sing-box 1.12+
                if ts_auth_key and ts_exit_node:
                    remote_data["endpoints"] = [{
                        "type": "tailscale",
                        "tag": ts_hostname + "-ep",
                        "auth_key": ts_auth_key,
                        "ephemeral": True,
                        "hostname": ts_hostname,
                        "accept_routes": True,
                        "advertise_exit_node": False,
                        "udp_timeout": "5m",
                        "domain_resolver": "dns-remote",
                        "exit_node": ts_exit_node
                    }]
            # fmt: on
                    for item in remote_data["outbounds"]:
                        if item.get("type") == "urltest" or item.get("type") == "selector":
                            item["outbounds"].append(ts_hostname + "-ep")

            body = json.dumps(remote_data, indent=2).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        except Exception as e:
            self.send_response(500)
            self.end_headers()
            msg = f"Error: {str(e)}"
            self.wfile.write(msg.encode())


if __name__ == "__main__":
    port = int(os.getenv("CONFIG_SERVER_PORT", 8851))
    http.server.HTTPServer(("0.0.0.0", port), Handler).serve_forever()
