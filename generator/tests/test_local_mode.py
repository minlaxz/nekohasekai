import json
from pathlib import Path

import pytest

from core import main


@pytest.fixture
def temp_project(tmp_path: Path, monkeypatch):
    """
    Fake local filesystem layout
    """
    monkeypatch.chdir(tmp_path)

    (tmp_path / "configs").mkdir()
    (tmp_path / "public").mkdir()
    (tmp_path / "certs").mkdir()

    (tmp_path / "configs/inbounds.json").write_text(
        json.dumps({"inbounds": [{}]})
    )

    (tmp_path / "public/outbounds.json").write_text(
        json.dumps({"outbounds": [{}]})
    )

    (tmp_path / "users.yaml").write_text(
        "users:\n  - name: test\n    password: pass\n    uuid: uuid123\n"
    )

    (tmp_path / "certs/certificate.crt").write_text("CERT")
    (tmp_path / "certs/ech.config").write_text("ECH")
    (tmp_path / "certs/private.key").write_text("PRIV")
    (tmp_path / "certs/public.key").write_text("PUB")

    yield tmp_path


def test_local_mode_generates_files(temp_project, monkeypatch):
    monkeypatch.setenv("START_PORT", "10000")
    monkeypatch.setenv("TLS__SERVER_NAME", "mozilla.org")
    monkeypatch.setenv("HYSTERIA2__OBFS_PASSWORD", "password123")

    # prevent curl
    monkeypatch.setattr(
        "singbox_config.core.get_server_ip",
        lambda: "127.0.0.1",
    )

    main(local_mode=True)

    assert Path("configs/inbounds.json").exists()
    assert Path("public/outbounds.json").exists()
    assert Path("public/users.json").exists()
