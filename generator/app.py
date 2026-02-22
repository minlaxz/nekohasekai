import logging
import typer

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
    cert_path: str = typer.Option(
        "certs/certificate.crt",
        "--cert-path",
        help="Path to certificate file",
    ),
    private_key_path: str = typer.Option(
        "certs/private.key",
        "--private-key-path",
        help="Path to private key file",
    ),
    ech_config_path: str = typer.Option(
        "certs/ech.config",
        "--ech-config-path",
        help="Path to ech config file",
    ),
    ech_key_path: str = typer.Option(
        "certs/ech.key",
        "--ech-key-path",
        help="Path to ech key file",
    ),
    r_private_key_path: str = typer.Option(
        "certs/reality_private.key",
        "--r-private-key-path",
        help="Path to reality private key file",
    ),
    r_public_key_path: str = typer.Option(
        "certs/reality_public.key",
        "--r-public-key-path",
        help="Path to reality public key file",
    ),
    inbounds_template: str = typer.Option(
        "server.template.json",
        "--inbounds-template",
        help="Path to inbounds template json file",
    ),
    outbounds_template: str = typer.Option(
        "client.template.json",
        "--outbounds-template",
        help="Path to outbounds template json file",
    ),
    users_template: str = typer.Option(
        "users.yaml",
        "--users-template",
        help="Path to users template yaml file"
    )
):
    """
    Generate sing-box configuration files.
    """
    logging.getLogger().setLevel(logging.DEBUG if (debug or local) else logging.INFO)

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
        certificate_path=cert_path,
        private_key_path=private_key_path,
        ech_config_path=ech_config_path,
        ech_key_path=ech_key_path,
        r_private_key_path=r_private_key_path,
        r_public_key_path=r_public_key_path,
        inbounds_template=inbounds_template,
        outbounds_template=outbounds_template,
        users_template=users_template,
        inbounds_output="inbounds.jsonc",
        outbounds_output="outbounds.jsonc",
        users_output="users.jsonc",
    )
    typer.echo("Generation completed.")


if __name__ == "__main__":
    app()
