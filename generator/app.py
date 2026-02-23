import typer
import logging

try:
    from .core import main
except ImportError:
    from core import main

try:
    from .helpers import run_shell, logger, error_handler
except ImportError:
    from helpers import run_shell, logger, error_handler


app = typer.Typer(
    help="Sing-box config generator",
    invoke_without_command=True,
)


@app.callback()
def main_callback(ctx: typer.Context):
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


@app.command()
def init(
    local: bool = typer.Option(
        False,
        "--local",
        help="Run in local/test mode (no ./data/ writes and read package resources)",
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        help="Enable debug logging",
    ),
    download: bool = typer.Option(
        False,
        "--download/--no-download",
        help="Whether to download the sing-box binary",
    ),
    generate_certs: bool = typer.Option(
        False,
        "--generate-certs/--no-generate-certs",
        help="Whether to generate TLS certificates and keys",
    ),
    tls_server_name: str = typer.Option(
        "",
        "--tls-server-name",
        help="Server name for TLS configurations, skip if empty",
    ),
    ech_server_name: str = typer.Option(
        "",
        "--ech-server-name",
        help="Server name for ECH configurations, skip if empty",
    ),
    copy_skeleton: bool = typer.Option(
        False,
        "--copy-skeleton/--no-copy-skeleton",
        help="Whether to copy skeleton configuration files to the data directory",
    ),
) -> None:
    """
    Download sing-box binary and create template files if they don't exist.
    """
    logger.setLevel(logging.DEBUG if debug else logging.INFO)

    typer.echo("Initialization Started")
    run_shell("templates.sh", "", local_mode=local)

    try:
        if download:
            run_shell("download-sing-box.sh", "", local_mode=local)

        if generate_certs:
            if not tls_server_name:
                raise ValueError(
                    "--tls-server-name must be provided when --generate-certs is enabled."
                )
            if not ech_server_name:
                raise ValueError(
                    "--ech-server-name must be provided when --generate-certs is enabled."
                )

            run_shell("generate-tls-keypair.sh", f"{tls_server_name}", local_mode=local)
            run_shell("generate-ech-keypair.sh", f"{ech_server_name}", local_mode=local)
            run_shell("generate-reality-keypair.sh", "", local_mode=local)

    except ValueError as e:
        error_handler(e, "In local mode, ensure that --local flag is also set.")

    typer.echo("Initialization completed.")


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
    certs_dir: str = typer.Option(
        "~/.sekai-generator/certs",
        "--certs-dir",
        help="Directory to store generated certificates and keys",
    ),
):
    """
    Generate sing-box configuration files.
    """
    logger.setLevel(logging.DEBUG if debug else logging.INFO)

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
        certs_dir=certs_dir,
        inbounds_template="server.template.json",
        outbounds_template="client.template.json",
        users_template="users.yaml",
        inbounds_output="~/.sekai-generator/configs/inbounds.json",
        outbounds_output="~/.sekai-generator/public/outbounds.json",
        users_output="~/.sekai-generator/public/users.json",
    )
    typer.echo("Generation completed.")


if __name__ == "__main__":
    app()
