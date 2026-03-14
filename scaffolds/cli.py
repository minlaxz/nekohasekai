import json
import subprocess
import logging
from typing import Any
import typer
import time

logging.basicConfig(
    level=logging.NOTSET, format="%(asctime)s - %(levelname)s - %(message)s"
)

IPIFY_URL = "https://api.ipify.org"
FILES = ["users.json", "configs/inbounds.json", "public/outbounds.json"]

app = typer.Typer(help="Sing-box config generator")


def load(path: str):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        logging.warning("Missing %s", path)


def save(path: str, data: dict[str, Any]):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def get_server_ip():
    try:
        ip = subprocess.run(
            ["curl", "-s", IPIFY_URL], capture_output=True, text=True, check=True
        ).stdout.strip()
        return ip or "127.0.0.1"
    except Exception:
        return "127.0.0.1"


@app.command()
def download(
    version: str = typer.Option("latest", help="Sing-box version to download"),
    arch: str = typer.Option("linux-amd64", help="Architecture of the binary"),
    force: bool = typer.Option(False, help="Force download even if binary exists"),
):
    """Download the latest sing-box binary from GitHub releases."""

    if (
        not force
        and subprocess.run(["which", "sing-box"], capture_output=True).returncode == 0
    ):
        typer.secho(
            "cli: sing-box binary already exists, use --force to overwrite.",
            fg=typer.colors.YELLOW,
        )
        return

    if version == "latest":
        result = subprocess.run(
            [
                "curl",
                "-s",
                "https://api.github.com/repos/SagerNet/sing-box/releases/latest",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        data = json.loads(result.stdout)
        version = data["name"].split("-")[0]
    else:
        version = "1.13.0"

    try:
        subprocess.run(
            [
                "curl",
                "-sL",
                f"https://github.com/SagerNet/sing-box/releases/download/v{version}/sing-box-{version}-{arch}.tar.gz",
                "-o",
                "/tmp/sing-box.tar.gz",
            ],
            check=True,
        )

        subprocess.run(
            [
                "tar",
                "-xzf",
                "/tmp/sing-box.tar.gz",
                "-C",
                ".",
                "--strip-components",
                "1",
            ],
            check=True,
        )

        subprocess.run(["rm", "-rf", "/tmp/sing-box.tar.gz", "LICENSE"], check=True)

    except subprocess.CalledProcessError as e:
        logging.error("Failed to download sing-box: %s", e)
        raise typer.Exit(code=1)
    typer.secho("cli: download complete.", fg=typer.colors.GREEN, bold=True)


@app.command()
def generate(
    ip: str = typer.Option(get_server_ip(), help="ShadowTLS server IP address"),
    port: int = typer.Option(help="ShadowTLS listen port"),
    tls_server_name: str = typer.Option("mozilla.org", help="TLS server name"),
    tls_server_port: int = typer.Option(443, help="TLS server port"),
):
    data: dict[str, Any] = {f: load(f) for f in FILES if load(f)}

    users = data.get("users.json", {}).get("users", [])
    inbounds = data.get("configs/inbounds.json", {}).get("inbounds", [])
    outbounds = data.get("public/outbounds.json", {}).get("outbounds", [])

    for i in inbounds:
        match i.get("type"):
            case "shadowtls":
                i.update({
                    "users": users,
                    "listen_port": port,
                    "handshake": {
                        "server": tls_server_name,
                        "server_port": tls_server_port,
                    },
                })
            case "shadowsocks":
                i.update({
                    "listen_port": port - 1,
                })
            case _:
                pass

    for o in outbounds:
        match o.get("tag"):
            case "shadowsocks-udp":
                o.update({
                    "server": ip,
                    "server_port": port - 1,
                })
            case "shadowtls":
                o.update({
                    "server": ip,
                    "server_port": port,
                    "tls": {"server_name": tls_server_name},
                })
            case _:
                pass

    if "users.json" in data:
        save("public/users.json", data["users.json"])
    if "configs/inbounds.json" in data:
        save("configs/inbounds.json", data["configs/inbounds.json"])
    if "public/outbounds.json" in data:
        save("public/outbounds.json", data["public/outbounds.json"])

    typer.secho("cli: generate complete.", fg=typer.colors.GREEN, bold=True)


@app.command()
def register():
    users = load("users.json")
    if not users:
        logging.warning("No users to register.")
        return
    for user in users.get("users", []):
        try:
            command = f'curl -X POST http://127.0.0.1:8888/server/v1/users -H \'Content-Type: application/json\' -d \'{{"username": "{user["name"]}", "uPSK": "{user["password"]}"}}\''
            subprocess.run(command, shell=True, check=True)
            typer.secho(f"cli: registered user {user['name']}", fg=typer.colors.GREEN)
        except subprocess.CalledProcessError as e:
            logging.error("Failed to register user %s: %s", user["name"], e)
            # raise typer.Exit(code=1)
        finally:
            time.sleep(1)
    typer.secho("cli: register complete.", fg=typer.colors.GREEN, bold=True)


if __name__ == "__main__":
    app()
