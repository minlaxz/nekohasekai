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
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        platform = query.get("platform", [""])[0].split("&")
        is_android = "android" in platform
        is_ios = "ios" in platform

        # version=11 or version=12 -> sing-box version 1.11 or 1.12
        version = query.get("version", ["12"])[0]

        private_nextdns_path = query.get("nextdns-path", [""])[0]

        # ipv6-onlu=1 -> enable ipv6 (not stable yet)
        # is_ipv6 = query.get("ipv6-only", ["0"])[0] == "1"

        if path != "/client.json":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")
            return

        try:
            with open(LOCAL_JSON_PATH) as f:
                local_data = json.load(f)

            with urllib.request.urlopen(REMOTE_JSON_URL) as r:
                remote_data = json.load(r)

            replaced = []
            for item in remote_data.get("outbounds", []):
                if item == "<INBOUND_REPLACE>":
                    replaced.append(local_data)
                else:
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
                        "detour": "direct"
                    },
                    {
                        "tag": "dns-direct",
                        "address": "1.1.1.1",
                        "detour": "direct"
                    }
                ]
            else: # default to version 1.12+
                remote_data["dns"]["servers"] = [
                    {
                        "tag": "dns-remote",
                        "type": "https",
                        "server": "dns.nextdns.io",
                        "path": private_nextdns_path if private_nextdns_path else "/",
                        "domain_resolver": "dns-direct"
                    },
                    {
                        "tag": "dns-direct",
                        "type": "udp",
                        "server": "1.1.1.1"
                    }
                ]
                remote_data["route"]["default_domain_resolver"] = {
                    "server": "dns-direct",
                    "rewrite_ttl": 60,
                    "client_subnet": "1.1.1.1"
                }
            # fmt: on

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
