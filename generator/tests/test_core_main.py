from typing import Any, Dict, List
import pytest
from generator.core import main


def test_main_happy_path(monkeypatch: pytest.MonkeyPatch):
    # Fake input templates
    fake_inbounds: Dict[str, Any] = {
        "inbounds": [
            {
                "type": "vless",
                "users": [],
                "tls": {"server_name": ""},
            }
        ]
    }

    fake_outbounds: Dict[str, Any] = {
        "outbounds": [
            {
                "tls": {
                    "server_name": "",
                    "certificate": [],
                    "reality": {"public_key": ""},
                    "ech": {"config": []},
                }
            }
        ]
    }

    fake_users = {"users": [{"name": "u1", "uuid": "123", "password": "pw"}]}

    def fake_read_file(
        filename: str, as_type: str = "", local_mode: bool = False
    ) -> Any:
        match filename:
            case "server.template.json":
                return fake_inbounds
            case "client.template.json":
                return fake_outbounds
            case "users.yaml":
                return fake_users
            case _:
                return []

    writes: List[Any] = []

    def fake_write_file(data: Any, filename: str, local_mode: bool = False):
        writes.append((filename, data))

    monkeypatch.setattr("generator.core.read_file", fake_read_file)
    monkeypatch.setattr("generator.core.write_file", fake_write_file)
    monkeypatch.setattr(
        "generator.core.get_server_ip", lambda *args, **kwargs: "1.2.3.4"
    )

    main(
        local_mode=True,
        tls_server_name="example.com",
        obfs_password="secret",
        inbounds_template="server.template.json",
        outbounds_template="client.template.json",
        users_template="users.yaml",
        inbounds_output="in.json",
        outbounds_output="out.json",
        users_output="users.json",
    )

    assert len(writes) == 3
