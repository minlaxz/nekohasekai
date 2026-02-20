import pytest
import subprocess
from generator.core import (
    read_env,
    env_is_true,
    resolve_path,
    BASE_DIR,
    TEST_DIR,
    write_file,
    get_server_ip,
)


def test_resolve_path_local():
    path = resolve_path("file.json", local_mode=True)
    assert path == TEST_DIR / "file.json"


def test_resolve_path_prod():
    path = resolve_path("file.json", local_mode=False)
    assert path == BASE_DIR / "file.json"


def test_read_env_required_missing():
    with pytest.raises(ValueError):
        read_env("MISSING_ENV")


def test_read_env_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("FOO", raising=False)
    assert read_env("FOO", default="bar", required=False) == "bar"


def test_env_is_true(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FLAG", "true")
    assert env_is_true("FLAG") is True

    monkeypatch.setenv("FLAG", "false")
    assert env_is_true("FLAG") is False


def test_write_file_called(monkeypatch: pytest.MonkeyPatch):
    written = {}

    def fake_open(*args: ..., **kwargs: ...):
        class FakeFile:
            def write(self, data: ...):
                written["data"] = data

            def __enter__(self):
                return self

            def __exit__(self, *exc: object):
                pass

        return FakeFile()

    monkeypatch.setattr("pathlib.Path.open", fake_open)

    def fake_mkdir(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr("pathlib.Path.mkdir", fake_mkdir)

    write_file({"a": 1}, "out.json", local_mode=True)
    assert written


def test_get_server_ip_local_mode_skips_network(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SERVER_IP", raising=False)

    def should_not_be_called(*args: ..., **kwargs: ...):
        raise AssertionError("subprocess.run should not be called in local mode")

    monkeypatch.setattr("generator.core.subprocess.run", should_not_be_called)
    assert get_server_ip(local_mode=True) == "127.0.0.1"


def test_get_server_ip_falls_back_on_failure(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SERVER_IP", "10.20.30.40")

    def fail_run(*args: ..., **kwargs: ...):
        raise subprocess.CalledProcessError(returncode=1, cmd="curl")

    monkeypatch.setattr("generator.core.subprocess.run", fail_run)
    assert get_server_ip() == "10.20.30.40"
