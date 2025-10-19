import http.server, json, urllib.request, os, io

LOCAL_JSON_PATH = os.getenv("LOCAL_JSON_PATH", "/data/local.json")
REMOTE_JSON_URL = os.getenv("REMOTE_JSON_URL", "https://raw.githubusercontent.com/minlaxz/nekohasekai/refs/heads/main/singbox/v2/sing-box-template")

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/client.json":
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
    port = int(os.getenv("PORT", 8851))
    http.server.HTTPServer(("0.0.0.0", port), Handler).serve_forever()
