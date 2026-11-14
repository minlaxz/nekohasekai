import inspect
import os
import sys

from fastapi import HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import main  # noqa: E402

HELP = os.path.join(os.path.dirname(__file__), "..", "templates", "help.html")


def test_help_lists_every_config_param():
    with open(HELP) as f:
        html = f.read()
    sig = inspect.signature(main.read_config).parameters
    params = [getattr(p.default, "alias", None) or n for n, p in sig.items() if n != "request"]
    assert "rr.ip_cidr" in params  # the alias, which is what users type
    missing = [n for n in params if f"<code>{n}</code>" not in html]
    assert not missing, f"add to api/templates/help.html: {missing}"


def test_help_is_404_without_valid_user(monkeypatch):
    def reject(j, k):
        raise HTTPException(status_code=400)

    monkeypatch.setattr(main, "verify_user", reject)
    r = TestClient(main.app).get("/help?j=alice&k=wrong")
    assert r.status_code == 404
    assert r.json() == TestClient(main.app).get("/no-such-path").json()


def test_help_renders_for_valid_user(monkeypatch):
    monkeypatch.setattr(main, "verify_user", lambda j, k: None)
    r = TestClient(main.app).get("/help?j=alice&k=a%2Bb==")
    assert r.status_code == 200
    assert "j=alice&amp;k=a%2Bb%3D%3D" in r.text


def test_schema_is_off():
    client = TestClient(main.app)
    assert all(client.get(p).status_code == 404 for p in ("/docs", "/redoc", "/openapi.json"))
