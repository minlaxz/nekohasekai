from typing import Dict, Tuple
import subprocess
from pathlib import Path
import base64
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives import serialization
import typer
import importlib.resources as resources

BASE_DIR = Path("./data")
TEST_DIR = Path("./test_data")


def run_bash(filename: str, argument: str, local_mode: bool = False) -> None:
    """
    Runs a bash script with a given argument.
    """
    if local_mode:
        script_path = "./scripts/" + filename
    else:
        script_path = str(
            resources.files(__package__).joinpath("scripts").joinpath(filename)
        )

    try:
        # Run the script using subprocess.run
        # We pass the command and its argument as a list
        result = subprocess.run(
            [script_path, argument],
            check=True,
        )
        typer.echo(f"Bash script output:\n{result.stdout}")
        typer.echo("Bash script executed successfully.")

    except subprocess.CalledProcessError as e:
        typer.echo(f"Error executing bash script: {e}", err=True)
        # Exit with a non-zero code to indicate failure in the CLI
        raise typer.Exit(code=1)
    except FileNotFoundError:
        typer.echo(f"Error: The script file was not found at {script_path}", err=True)
        typer.echo(
            "Please make sure the script exists and has executable permissions (chmod +x).",
            err=True,
        )
        raise typer.Exit(code=1)


def resolve_path(filename: str, local_mode: bool) -> Path:
    base = TEST_DIR if local_mode else BASE_DIR
    return base / filename


def is_file_exists(paths: Tuple[str, ...] | str, local_mode: bool = False) -> bool:
    if isinstance(paths, str):
        paths = (paths,)
    for path in paths:
        _path = resolve_path(path, local_mode=local_mode)
        if not (_path.exists() and _path.is_file()):
            return False
    return True


def generate_certs(
    certs_dir: str,
    tls_server_name: str,
    local_mode: bool = False,
) -> None:

    _certs_dir = resolve_path(certs_dir, local_mode=local_mode)
    _certs_dir.mkdir(parents=True, exist_ok=True)

    private_key = _certs_dir / "private.key"
    cert_file = _certs_dir / "certificate.crt"

    subprocess.run(
        [
            "openssl",
            "ecparam",
            "-genkey",
            "-name",
            "prime256v1",
            "-out",
            str(private_key),
        ],
        check=True,
    )

    subprocess.run(
        [
            "openssl",
            "req",
            "-new",
            "-x509",
            "-days",
            "36500",
            "-key",
            str(private_key),
            "-out",
            str(cert_file),
            "-subj",
            f"/CN={tls_server_name}",
            "-addext",
            f"subjectAltName=DNS:{tls_server_name}",
        ],
        check=True,
    )


def generate_ech_keys(ech_domain_name: str) -> None:
    pass


def b64url_no_padding(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def generate_reality_keypair() -> Dict[str, str]:
    private_key = x25519.X25519PrivateKey.generate()
    public_key = private_key.public_key()

    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )

    public_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    return {
        "private": b64url_no_padding(private_bytes),
        "public": b64url_no_padding(public_bytes),
    }
