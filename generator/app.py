import logging
import typer
import os

try:
    from .core import main
except ImportError:
    from core import main

app = typer.Typer(help="Sing-box config generator")


@app.command()
def generate(
    local: bool = typer.Option(
        False,
        "--local",
        help="Run in local/test mode (no ./data/ writes)",
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        help="Enable debug logging",
    ),
    start_port: int = typer.Option(
        8820,
        "--start-port",
        help="Starting port number for generated configurations",
    ),
    tls_server_name: str = typer.Option(
        "mozilla.org",
        "--tls-server-name",
        help="Server name for TLS configurations",
    ),
    obfs_password: str = typer.Option(
        "password123",
        "--obfs-password",
        help="Password for obfuscation in Hysteria2 configurations",
    ),
    up_mbps: int = typer.Option(
        300,
        "--up-mbps",
        help="Upload speed in Mbps for generated configurations",
    ),
    down_mbps: int = typer.Option(
        300,
        "--down-mbps",
        help="Download speed in Mbps for generated configurations",
    ),
    up_mbps_factor: float = typer.Option(
        0.1,
        "--up-mbps-factor",
        help="Factor to adjust upload speed in generated configurations",
    ),
    down_mbps_factor: float = typer.Option(
        0.1,
        "--down-mbps-factor",
        help="Factor to adjust download speed in generated configurations",
    ),
):
    """
    Generate sing-box configuration files.
    """
    logging.getLogger().setLevel(logging.DEBUG if (debug or local) else logging.INFO)
    if local and not os.path.exists("./test_data/"):
        raise FileNotFoundError("./test_data/ directory not found.")

    typer.echo("Config generation Started")
    main(
        local_mode=local,
        start_port=start_port,
        tls_server_name=tls_server_name,
        obfs_password=obfs_password,
        up_mbps=up_mbps,
        down_mbps=down_mbps,
        up_mbps_factor=up_mbps_factor,
        down_mbps_factor=down_mbps_factor,
        inbounds_template="server.template.json",
        outbounds_template="client.template.json",
        users_template="users.yaml",
        inbounds_output="inbounds.jsonc",
        outbounds_output="outbounds.jsonc",
        users_output="users.jsonc",
        certificate_path="certs/certificate.crt",
        ech_config_path="certs/ech.config",
        private_key_path="certs/private.key",
        public_key_path="certs/public.key",
    )
    typer.echo("Generation completed.")


if __name__ == "__main__":
    app()
