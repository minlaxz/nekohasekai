from typing import Tuple
import logging
import sys
import subprocess
from pathlib import Path
import typer
import importlib.resources as resources

BASE_DIR = Path("./data")
TEST_DIR = Path("./test_data")

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------

LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"

logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)


def error_handler(eobj: Exception, extra_message: str = "") -> None:
    logger.error(f"Error: {eobj}")
    if extra_message:
        logger.error(extra_message)
    raise typer.Exit(code=1)


def run_shell(filename: str, argument: str, local_mode: bool = False) -> None:
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
        _ = subprocess.run(
            [script_path, argument],
            check=True,
        )
        # logger.info(f"Bash script output:\n{result.stdout}")
        typer.echo(f"{filename} executed successfully.")

    except subprocess.CalledProcessError as e:
        # logger.error(f"Error executing bash script: {e}")
        typer.echo(f"Error executing {filename}: {e}", err=True)
        raise typer.Exit(code=1)
    except FileNotFoundError:
        # logger.error(f"Error: The script file was not found at {script_path}")
        typer.echo(f"Error: The script file was not found at {script_path}", err=True)
        typer.echo(
            "Please make sure the script exists and has executable permissions (chmod +x).",
            err=True,
        )
        raise typer.Exit(code=1)


def resolve_path(filename: str, local_mode: bool, no_resolve: bool = False) -> Path:
    if no_resolve:
        return Path(filename)
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
