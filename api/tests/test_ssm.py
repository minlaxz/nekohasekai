import base64
import json
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.main import app  # noqa: E402
from app.routes import ssm  # noqa: E402
from app.utils import ssm_key  # noqa: E402

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

    posted = {}

    async def add(username, upsk):
        upstream.add(username)
        posted[username] = upsk

    async def remove(username):
        upstream.discard(username)

    monkeypatch.setattr(ssm, "_upstream_usernames", names)
    monkeypatch.setattr(ssm, "create_user_in_memory", add)
    monkeypatch.setattr(ssm, "delete_user_in_memory", remove)
    c = TestClient(app)
    c.users_path = users
    c.upstream = upstream
    c.posted = posted
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
    assert 'name="username"' in r.text and 'name="months"' in r.text
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
    # ssm-api gets the SS-2022 key; the file and the user keep `k` (#24)
    assert client.posted["bob"] == ssm_key(body["uPSK"])
    assert json.loads(client.users_path.read_text())["users"][-1]["password"] == body["uPSK"]


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
    assert r.json() == {"users": [{"username": "alice", "downlinkBytes": 1, "expires_at": None, "expired": False, "disabled": False}]}
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


# --- reconcile --------------------------------------------------------------


def test_reconcile_posts_derived_keys_and_skips_bad_entries(client, monkeypatch):
    k = "nj75pm4nlaslo8xm8xtK=="
    client.users_path.write_text(json.dumps({"users": [
        {"name": "alice", "password": "a" * 20 + "==", "admin": False},
        {"name": "bad", "password": "insecure-user123==", "admin": False},
        {"name": "bob", "password": k, "admin": False},
    ]}))
    posted = []

    async def add(username, upsk):
        posted.append({"username": username, "uPSK": upsk})

    monkeypatch.setattr(ssm, "create_user_in_memory", add)
    import asyncio
    asyncio.run(ssm.reconcile_users())
    assert posted == [{"username": "bob", "uPSK": "nj75pm4nlaslo8xm8xtKnj75"}]

# --- expiry -----------------------------------------------------------------

import asyncio  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def frozen(monkeypatch):
    monkeypatch.setattr(ssm, "_now", lambda: NOW)
    return NOW


def _entry(client, name):
    return next(u for u in json.loads(client.users_path.read_text())["users"] if u["name"] == name)


def _set_expiry(client, name, expires_at):
    users = json.loads(client.users_path.read_text())
    next(u for u in users["users"] if u["name"] == name)["expires_at"] = expires_at
    client.users_path.write_text(json.dumps(users))


def _add_entry(client, name, **extra):
    users = json.loads(client.users_path.read_text())
    users["users"].append({"name": name, "password": name[0] * 20 + "==", "admin": False, **extra})
    client.users_path.write_text(json.dumps(users))


def test_create_default_is_trial_only(client, frozen):
    body = client.post("/ssm/create", data={"username": "bob"}, headers=JSON).json()
    assert body["expires_at"] == "2026-10-08T12:00:00+00:00"
    assert _entry(client, "bob")["expires_at"] == body["expires_at"]


def test_create_months_adds_trial(client, frozen):
    body = client.post("/ssm/create", data={"username": "bob", "months": 3}, headers=JSON).json()
    assert body["expires_at"] == "2027-01-08T12:00:00+00:00"


def test_create_html_shows_expiry(client, frozen):
    r = client.post("/ssm/create", data={"username": "bob", "months": 1}, headers=HTML)
    assert "2026-11-08T12:00:00+00:00" in r.text


@pytest.mark.parametrize("months", [-1, 7, "x"])
def test_create_months_out_of_range_is_400(client, months):
    r = client.post("/ssm/create", data={"username": "bob", "months": months}, headers=JSON)
    assert r.status_code == 400
    assert "bob" not in client.upstream


@pytest.mark.parametrize(
    "start,months,end",
    [
        ("2026-01-31", 1, "2026-02-28"),
        ("2028-01-31", 1, "2028-02-29"),
        ("2026-10-31", 4, "2027-02-28"),
        ("2026-05-15", 6, "2026-11-15"),
        ("2026-12-01", 1, "2027-01-01"),
    ],
)
def test_add_months_is_calendar(start, months, end):
    dt = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
    assert ssm.add_months(dt, months).date().isoformat() == end


def test_reconcile_removes_expired_and_adds_live(client, frozen):
    _set_expiry(client, "alice", "2026-10-05T11:59:00+00:00")  # expired, still in ssm-api
    _add_entry(client, "carol", expires_at="2026-12-01T00:00:00+00:00")  # live, missing from ssm-api
    _add_entry(client, "dan")  # no Expiry: never expires
    _add_entry(client, "eve", expires_at="2026-01-01")  # hand-edited, no zone: still expired
    client.upstream.add("stranger")  # in ssm-api only: left alone
    asyncio.run(ssm.reconcile_users())
    assert client.upstream == {"carol", "dan", "stranger"}
    assert _file_names(client) == ["alice", "carol", "dan", "eve"]


def test_renew_expired_counts_from_now(client, frozen):
    _set_expiry(client, "alice", "2026-09-01T00:00:00+00:00")
    client.upstream.discard("alice")
    r = client.post("/ssm/renew", data={"username": "alice", "months": 1}, headers=JSON)
    assert r.status_code == 200, r.text
    assert r.json() == {"username": "alice", "expires_at": "2026-11-05T12:00:00+00:00"}
    assert "alice" in client.upstream
    assert _entry(client, "alice")["password"] == "a" * 20 + "=="


def test_renew_live_extends_current_expiry(client, frozen):
    _set_expiry(client, "alice", "2026-10-20T00:00:00+00:00")
    r = client.post("/ssm/renew", data={"username": "alice", "months": 2}, headers=JSON)
    assert r.json()["expires_at"] == "2026-12-20T00:00:00+00:00"


def test_renew_without_expiry_starts_now(client, frozen):
    r = client.post("/ssm/renew", data={"username": "alice", "months": 1}, headers=JSON)
    assert r.json()["expires_at"] == "2026-11-05T12:00:00+00:00"


def test_renew_html_for_browser(client, frozen):
    r = client.post("/ssm/renew", data={"username": "alice", "months": 1}, headers=HTML)
    assert r.status_code == 200 and "2026-11-05T12:00:00+00:00" in r.text


@pytest.mark.parametrize("months", [0, 7, ""])
def test_renew_months_out_of_range_is_400(client, months):
    r = client.post("/ssm/renew", data={"username": "alice", "months": months}, headers=JSON)
    assert r.status_code == 400
    assert "expires_at" not in _entry(client, "alice")


def test_renew_unknown_is_404(client):
    assert client.post("/ssm/renew", data={"username": "ghost", "months": 1}, headers=JSON).status_code == 404


def test_stats_lists_expired_users(client, monkeypatch, frozen):
    _set_expiry(client, "alice", "2026-12-01T00:00:00+00:00")
    _add_entry(client, "old", expires_at="2026-01-01T00:00:00+00:00")

    async def stats():
        return [{"username": "alice", "downlinkBytes": 1}]

    monkeypatch.setattr(ssm, "get_stats", stats)
    rows = client.get("/ssm/server/v1/users", headers=JSON).json()["users"]
    assert rows == [
        {"username": "alice", "downlinkBytes": 1, "expires_at": "2026-12-01T00:00:00+00:00", "expired": False,
         "disabled": False},
        {"username": "old", "uPSK": "o" * 20 + "==", "expires_at": "2026-01-01T00:00:00+00:00", "expired": True,
         "disabled": False},
    ]
    html = client.get("/ssm/server/v1/users", headers=HTML).text
    assert "old" in html and "(expired)" in html and html.count("(expired)") == 1
    assert 'action="/ssm/expiry"' in html and 'value="2026-12-01T00:00"' in html


def test_reconcile_warns_on_duplicate_psk(client, frozen, caplog):
    _add_entry(client, "alice-mac")
    users = json.loads(client.users_path.read_text())
    next(u for u in users["users"] if u["name"] == "alice-mac")["password"] = "a" * 20 + "=="
    client.users_path.write_text(json.dumps(users))
    with caplog.at_level("WARNING"):
        asyncio.run(ssm.reconcile_users())
    assert "duplicate PSK shared by ['alice', 'alice-mac']" in caplog.text


# --- set expiry -------------------------------------------------------------


def test_set_expiry_past_removes_user(client, frozen):
    r = client.post("/ssm/expiry", data={"username": "alice", "expires_at": "2026-01-01T00:00"}, headers=JSON)
    assert r.status_code == 200, r.text
    assert r.json() == {"username": "alice", "expires_at": "2026-01-01T00:00:00+00:00"}
    assert "alice" not in client.upstream


def test_set_expiry_empty_means_never_and_restores(client, frozen):
    _set_expiry(client, "alice", "2026-01-01T00:00:00+00:00")
    client.upstream.discard("alice")
    r = client.post("/ssm/expiry", data={"username": "alice", "expires_at": ""}, headers=JSON)
    assert r.json() == {"username": "alice", "expires_at": None}
    assert "expires_at" not in _entry(client, "alice") and "alice" in client.upstream


def test_set_expiry_keeps_explicit_zone(client, frozen):
    r = client.post(
        "/ssm/expiry", data={"username": "alice", "expires_at": "2027-01-01T09:00:00+09:00"}, headers=JSON
    )
    assert r.json()["expires_at"] == "2027-01-01T09:00:00+09:00"


def test_set_expiry_bad_value_is_400(client):
    r = client.post("/ssm/expiry", data={"username": "alice", "expires_at": "tomorrow"}, headers=JSON)
    assert r.status_code == 400 and "expires_at" in r.text
    assert "expires_at" not in _entry(client, "alice")


def test_set_expiry_unknown_is_404(client):
    r = client.post("/ssm/expiry", data={"username": "ghost", "expires_at": ""}, headers=JSON)
    assert r.status_code == 404


def test_set_expiry_html_redirects_to_stats(client, frozen):
    r = client.post(
        "/ssm/expiry",
        data={"username": "alice", "expires_at": "2027-01-01T00:00"},
        headers=HTML,
        follow_redirects=False,
    )
    assert r.status_code == 303 and r.headers["location"] == "/ssm/server/v1/users"
    assert _entry(client, "alice")["expires_at"] == "2027-01-01T00:00:00+00:00"


# --- disable / enable -------------------------------------------------------


def test_reconcile_keeps_disabled_users_out(client, frozen):
    _add_entry(client, "bob", disabled=True)
    client.upstream.add("bob")
    _add_entry(client, "carol", disabled=True, expires_at="2026-01-01T00:00:00+00:00")
    _add_entry(client, "dan", disabled=False)
    asyncio.run(ssm.reconcile_users())
    assert client.upstream == {"alice", "dan"}


def test_disable_removes_user_and_keeps_expiry(client, frozen):
    _set_expiry(client, "alice", "2026-12-01T00:00:00+00:00")
    r = client.post("/ssm/disable", data={"username": "alice"}, headers=JSON)
    assert r.status_code == 200, r.text
    assert r.json() == {"username": "alice", "disabled": True}
    assert "alice" not in client.upstream
    assert _entry(client, "alice")["disabled"] is True
    assert _entry(client, "alice")["expires_at"] == "2026-12-01T00:00:00+00:00"
    # idempotent
    assert client.post("/ssm/disable", data={"username": "alice"}, headers=JSON).status_code == 200


def test_enable_restores_user(client, frozen):
    client.post("/ssm/disable", data={"username": "alice"}, headers=JSON)
    r = client.post("/ssm/enable", data={"username": "alice"}, headers=JSON)
    assert r.json() == {"username": "alice", "disabled": False}
    assert "alice" in client.upstream and "disabled" not in _entry(client, "alice")
    assert client.post("/ssm/enable", data={"username": "alice"}, headers=JSON).status_code == 200


def test_enable_expired_user_stays_out(client, frozen):
    _set_expiry(client, "alice", "2026-01-01T00:00:00+00:00")
    client.post("/ssm/disable", data={"username": "alice"}, headers=JSON)
    client.post("/ssm/enable", data={"username": "alice"}, headers=JSON)
    assert "alice" not in client.upstream


def test_set_expiry_does_not_enable(client, frozen):
    client.post("/ssm/disable", data={"username": "alice"}, headers=JSON)
    client.post("/ssm/expiry", data={"username": "alice", "expires_at": ""}, headers=JSON)
    assert "alice" not in client.upstream and _entry(client, "alice")["disabled"] is True


def test_delete_memory_only_user(client):
    client.upstream.add("stranger")
    assert client.post("/ssm/delete", data={"username": "stranger"}, headers=JSON).status_code == 200
    assert "stranger" not in client.upstream and _file_names(client) == ["alice"]


def test_delete_admin_not_in_ssm_api_is_403(client):
    _add_entry(client, "root", admin=True)
    assert client.post("/ssm/delete", data={"username": "root"}, headers=JSON).status_code == 403


def test_renew_does_not_enable(client, frozen):
    client.post("/ssm/disable", data={"username": "alice"}, headers=JSON)
    client.post("/ssm/renew", data={"username": "alice", "months": 1}, headers=JSON)
    assert "alice" not in client.upstream and _entry(client, "alice")["disabled"] is True


@pytest.mark.parametrize("path", ["/ssm/disable", "/ssm/enable"])
def test_disable_enable_unknown_or_memory_only_is_404(client, path):
    client.upstream.add("stranger")
    assert client.post(path, data={"username": "ghost"}, headers=JSON).status_code == 404
    assert client.post(path, data={"username": "stranger"}, headers=JSON).status_code == 404


@pytest.mark.parametrize("path", ["/ssm/disable", "/ssm/delete"])
def test_admin_entry_is_403(client, path):
    _add_entry(client, "root", admin=True)
    client.upstream.add("root")
    assert client.post(path, data={"username": "root"}, headers=JSON).status_code == 403
    assert "root" in client.upstream and "root" in _file_names(client)


@pytest.mark.parametrize("path", ["/ssm/disable", "/ssm/enable", "/ssm/delete"])
def test_disable_enable_delete_html_redirects_to_stats(client, frozen, path):
    r = client.post(path, data={"username": "alice"}, headers=HTML, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/ssm/server/v1/users"


def test_stats_lists_disabled_users_with_buttons(client, monkeypatch, frozen):
    _add_entry(client, "bob", disabled=True)
    _add_entry(client, "root", admin=True)

    async def stats():
        return [{"username": "alice"}, {"username": "root"}, {"username": "stranger"}]

    monkeypatch.setattr(ssm, "get_stats", stats)
    rows = client.get("/ssm/server/v1/users", headers=JSON).json()["users"]
    assert [(r["username"], r["disabled"]) for r in rows] == [
        ("alice", False), ("root", False), ("stranger", False), ("bob", True)
    ]
    html = client.get("/ssm/server/v1/users", headers=HTML).text
    assert "(disabled)" in html
    assert html.count('action="/ssm/disable"') == 1  # alice; not root (admin), not stranger (memory only)
    assert html.count('action="/ssm/enable"') == 1  # bob
    assert html.count('action="/ssm/delete"') == 3  # alice, stranger, bob; not root
    assert "confirm(" in html
