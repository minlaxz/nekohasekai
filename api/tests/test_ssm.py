import base64
import json
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.main import app  # noqa: E402
from app.routes import ssm  # noqa: E402

ADMIN = {"Authorization": "Basic " + base64.b64encode(b"admin:secret").decode()}
JSON = {**ADMIN, "Accept": "application/json"}
HTML = {**ADMIN, "Accept": "text/html,*/*;q=0.8"}


@pytest.fixture
def client(monkeypatch, tmp_path):
    users = tmp_path / "users.json"
    users.write_text(json.dumps({"users": [{"name": "alice", "password": "a" * 20 + "==", "admin": False}]}))
    monkeypatch.setattr(ssm, "APP_USERS_PATH", str(users))
    monkeypatch.setattr(ssm, "APP_HOST", "vpn.example")
    monkeypatch.setenv("APP_ADMIN_PASSWORD", "secret")
    monkeypatch.delenv("APP_ADMIN_USER", raising=False)

    upstream = {"alice"}

    async def names():
        return set(upstream)

    async def add(username, upsk):
        upstream.add(username)

    async def remove(username):
        upstream.discard(username)

    monkeypatch.setattr(ssm, "_upstream_usernames", names)
    monkeypatch.setattr(ssm, "create_user_in_memory", add)
    monkeypatch.setattr(ssm, "delete_user_in_memory", remove)
    c = TestClient(app)
    c.users_path = users
    c.upstream = upstream
    return c


def _file_names(client):
    return [u["name"] for u in json.loads(client.users_path.read_text())["users"]]


# --- auth -------------------------------------------------------------------


def test_no_credentials_is_401(client):
    assert client.post("/ssm/create", data={"username": "bob"}).status_code == 401
    assert client.get("/ssm/form").status_code == 401
    assert client.get("/ssm-transparent/server/v1/users").status_code == 401


def test_wrong_password_is_401(client):
    bad = {"Authorization": "Basic " + base64.b64encode(b"admin:nope").decode()}
    assert client.get("/ssm/form", headers=bad).status_code == 401


def test_unset_password_fails_closed(client, monkeypatch):
    monkeypatch.delenv("APP_ADMIN_PASSWORD")
    assert client.get("/ssm/form", headers=ADMIN).status_code == 401


def test_form_page_with_credentials(client):
    r = client.get("/ssm/form", headers=ADMIN)
    assert r.status_code == 200
    assert 'name="username"' in r.text
    assert "custom_upsk" not in r.text and "platform" not in r.text


# --- create -----------------------------------------------------------------


def test_create_json(client):
    r = client.post("/ssm/create", data={"username": "bob"}, headers=JSON)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["username"] == "bob"
    assert len(body["uPSK"]) == 22 and body["uPSK"].endswith("==")
    assert body["import_url"] == f"https://vpn.example/i?j=bob&k={body['uPSK']}"
    assert body["config_url"] == f"https://vpn.example/c?j=bob&k={body['uPSK']}"
    assert "bob" in client.upstream and "bob" in _file_names(client)


def test_create_html_for_browser(client):
    r = client.post("/ssm/create", data={"username": "bob"}, headers=HTML)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "https://vpn.example/c?j=bob&amp;k=" in r.text


def test_create_duplicate_is_409(client):
    r = client.post("/ssm/create", data={"username": "alice"}, headers=JSON)
    assert r.status_code == 409
    assert _file_names(client) == ["alice"]


@pytest.mark.parametrize("name", ["", "-bob", "bob!", "b" * 33, "a b"])
def test_create_bad_username_is_400(client, name):
    r = client.post("/ssm/create", data={"username": name}, headers=JSON)
    assert r.status_code == 400
    assert name not in client.upstream


@pytest.mark.parametrize("name", ["HP_HM", "kma-km-ios", "r1", "x" * 32])
def test_create_accepts_existing_name_shapes(client, name):
    assert client.post("/ssm/create", data={"username": name}, headers=JSON).status_code == 200


# --- delete -----------------------------------------------------------------


def test_delete(client):
    r = client.post("/ssm/delete", data={"username": "alice"}, headers=JSON)
    assert r.status_code == 200
    assert r.json() == {"deleted": "alice"}
    assert "alice" not in client.upstream and _file_names(client) == []


def test_delete_unknown_is_404(client):
    assert client.post("/ssm/delete", data={"username": "ghost"}, headers=JSON).status_code == 404


# --- stats ------------------------------------------------------------------


def test_stats_json(client, monkeypatch):
    async def stats():
        return [{"username": "alice", "downlinkBytes": 1}]

    monkeypatch.setattr(ssm, "get_stats", stats)
    r = client.get("/ssm/server/v1/users", headers=JSON)
    assert r.json() == {"users": [{"username": "alice", "downlinkBytes": 1}]}
    r = client.get("/ssm/server/v1/users", headers=HTML)
    assert r.headers["content-type"].startswith("text/html")


# --- docs -------------------------------------------------------------------


def test_openapi_hides_transparent_proxy(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/ssm/create" in paths and "/c" in paths
    assert not any(p.startswith("/ssm-transparent") for p in paths)


# --- transparent proxy ---------------------------------------------------------


def test_transparent_proxy_strips_admin_credential(client, monkeypatch):
    from app.routes import ssm_transparent

    seen = {}

    class FakeResp:
        content, status_code, headers = b"{}", 200, {"content-type": "application/json"}

    class FakeClient:
        def __init__(self, **kw): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): ...
        async def request(self, method, url, **kw):
            seen.update(kw["headers"])
            return FakeResp()

    monkeypatch.setattr(ssm_transparent.httpx, "AsyncClient", FakeClient)
    assert client.get("/ssm-transparent/server/v1/users", headers=ADMIN).status_code == 200
    assert "authorization" not in {k.lower() for k in seen}
    assert "host" not in {k.lower() for k in seen}
