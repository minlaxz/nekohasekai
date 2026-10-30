import base64
import json
import os
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.main import app  # noqa: E402
from app import store  # noqa: E402
from app.routes import ssm  # noqa: E402
from app.utils import ssm_key  # noqa: E402

ADMIN = {"Authorization": "Basic " + base64.b64encode(b"admin:secret").decode()}
JSON = {**ADMIN, "Accept": "application/json"}
HTML = {**ADMIN, "Accept": "text/html,*/*;q=0.8"}


@pytest.fixture
def client(monkeypatch, user_store):
    store.add(name="alice", password="a" * 20 + "==")
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
    c.upstream = upstream
    c.posted = posted
    return c


def _store_names(client):
    return [u["name"] for u in store.records()]


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
    assert "bob" in client.upstream and "bob" in _store_names(client)
    # ssm-api gets the SS-2022 key; the file and the user keep `k` (#24)
    assert client.posted["bob"] == ssm_key(body["uPSK"])
    assert store.get("bob")["password"] == body["uPSK"]


def test_create_html_for_browser(client):
    r = client.post("/ssm/create", data={"username": "bob"}, headers=HTML)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "https://vpn.example/c?j=bob&amp;k=" in r.text


def test_create_duplicate_is_409(client):
    r = client.post("/ssm/create", data={"username": "alice"}, headers=JSON)
    assert r.status_code == 409
    assert _store_names(client) == ["alice"]


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
    assert "alice" not in client.upstream and _store_names(client) == []


def test_delete_unknown_is_404(client):
    assert client.post("/ssm/delete", data={"username": "ghost"}, headers=JSON).status_code == 404


# --- stats ------------------------------------------------------------------


def test_stats_json(client, monkeypatch):
    async def stats():
        return [{"username": "alice", "downlinkBytes": 1}]

    monkeypatch.setattr(ssm, "get_stats", stats)
    r = client.get("/ssm/server/v1/users", headers=JSON)
    assert r.json() == {"users": [{"username": "alice", "downlinkBytes": 1, "expires_at": None, "expired": False, "disabled": False, "last_fetch": None}]}
    r = client.get("/ssm/server/v1/users", headers=HTML)
    assert r.headers["content-type"].startswith("text/html")


def test_last_fetch_kept_in_user_record(client, monkeypatch, frozen):
    import app.main as main
    from fastapi import HTTPException

    class FakeReader:
        def __init__(self, username, psk, **_):
            if psk != "good":
                raise HTTPException(status_code=403, detail="bad PSK")

        def unwarp(self):
            return {}

    async def stats():
        return [{"username": "alice", "downlinkBytes": 0}]

    monkeypatch.setattr(main, "Reader", FakeReader)
    monkeypatch.setattr(ssm, "get_stats", stats)
    assert not hasattr(ssm, "LAST_FETCH")

    def last_fetch():
        return store.get("alice")["last_fetch"]

    assert client.get("/c?j=alice&k=bad&dp=/q").status_code == 403
    assert client.get("/i?j=alice&k=good").status_code == 200
    assert last_fetch() is None
    assert client.get("/c?j=alice&k=good&dp=/q").status_code == 200
    assert last_fetch() == NOW.isoformat()
    assert ssm._ago(NOW.isoformat()) == "just now" and ssm._ago(None) == "never"

    # Restart: the stats page reads it back from the database, not process memory.
    rows = TestClient(app).get("/ssm/server/v1/users", headers=JSON).json()["users"]
    assert rows[0]["last_fetch"] == NOW.isoformat()

    assert client.post("/ssm/delete", data={"username": "alice"}, headers=JSON).status_code == 200
    assert client.post("/ssm/create", data={"username": "alice"}, headers=JSON).status_code == 200
    assert last_fetch() is None


# --- docs -------------------------------------------------------------------


def test_openapi_hides_transparent_proxy(client):
    paths = app.openapi()["paths"]  # schema is not served, but still built
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
    store.add(name="bad", password="insecure-user123==")
    store.add(name="bob", password=k)
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
    return store.get(name)


def _set_expiry(client, name, expires_at):
    store.update(name, expires_at=expires_at)


def _add_entry(client, name, **extra):
    store.add(name=name, password=name[0] * 20 + "==", **extra)


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
    assert _store_names(client) == ["alice", "carol", "dan", "eve"]


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
    assert _entry(client, "alice")["expires_at"] is None


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
         "disabled": False, "last_fetch": None},
        {"username": "old", "uPSK": "o" * 20 + "==", "expires_at": "2026-01-01T00:00:00+00:00", "expired": True,
         "disabled": False, "last_fetch": None},
    ]
    html = client.get("/ssm/server/v1/users", headers=HTML).text
    assert "old" in html and "(expired)" in html and html.count("(expired)") == 1
    assert 'action="/ssm/expiry"' in html and 'value="2026-12-01T00:00"' in html


def test_store_refuses_duplicate_psk(client):
    # SS-2022 identifies a user by key: two User records with one PSK would be one user to sing-box
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        store.add(name="alice-mac", password="a" * 20 + "==")
    assert _store_names(client) == ["alice"]


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
    assert _entry(client, "alice")["expires_at"] is None and "alice" in client.upstream


def test_set_expiry_keeps_explicit_zone(client, frozen):
    r = client.post(
        "/ssm/expiry", data={"username": "alice", "expires_at": "2027-01-01T09:00:00+09:00"}, headers=JSON
    )
    assert r.json()["expires_at"] == "2027-01-01T09:00:00+09:00"


def test_set_expiry_bad_value_is_400(client):
    r = client.post("/ssm/expiry", data={"username": "alice", "expires_at": "tomorrow"}, headers=JSON)
    assert r.status_code == 400 and "expires_at" in r.text
    assert _entry(client, "alice")["expires_at"] is None


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
    assert "alice" in client.upstream and _entry(client, "alice")["disabled"] is False
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
    assert "stranger" not in client.upstream and _store_names(client) == ["alice"]


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
    assert "root" in client.upstream and "root" in _store_names(client)


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


# --- User export ------------------------------------------------------------


def test_export_needs_admin(client):
    assert client.get("/ssm/export").status_code == 401


def test_export_csv(client, monkeypatch):
    _add_entry(client, "bob", expires_at="2026-10-08T12:00:00+00:00", disabled=True, warp_key="wk=", warp_ipv6="2606::1/128")
    _add_entry(client, "root", admin=True, ts_auth_key="ts-key")
    store.update("alice", last_fetch="2026-10-01T00:00:00+00:00")  # not exported
    r = client.get("/ssm/export", headers=ADMIN)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert r.headers["content-disposition"].startswith("attachment")
    assert r.headers["cache-control"] == "no-store"
    assert r.text.splitlines() == [
        "name,password,admin,expires_at,disabled,ts_auth_key,warp_key,warp_ipv6",
        f"alice,{'a' * 20}==,false,,false,,,",
        f"bob,{store.get('bob')['password']},false,2026-10-08T12:00:00+00:00,true,,wk=,2606::1/128",
        f"root,{store.get('root')['password']},true,,false,ts-key,,",
    ]


def test_dashboard_links_export(client, monkeypatch):
    async def stats():
        return []

    monkeypatch.setattr(ssm, "get_stats", stats)
    assert 'href="/ssm/export"' in client.get("/ssm/server/v1/users", headers=HTML).text


# --- User import ------------------------------------------------------------

HEADER = ",".join(ssm.CSV_FIELDS)
BOB = f"bob,{'b' * 20}==,false,,false,,,"


def _import(client, *lines, headers=JSON):
    body = "\n".join(lines) + "\n"
    return client.post(
        "/ssm/import", files={"file": ("users.csv", body, "text/csv")}, headers=headers, follow_redirects=False
    )


def test_import_adds_users_and_live_ones_reach_ssm_api(client, frozen):
    r = _import(
        client,
        HEADER,
        BOB,
        f"carol,{'c' * 20}==,false,2026-01-01T00:00:00+00:00,false,,,",  # Expired
        f"dave,{'d' * 20}==,false,,true,,,",  # Disabled
        f"erin,{'e' * 20}==,true,2027-01-01T00:00:00+00:00,false,ts-key,wk=,2606::1/128",
    )
    assert r.status_code == 200
    assert r.json() == {"added": ["bob", "carol", "dave", "erin"]}
    assert _store_names(client) == ["alice", "bob", "carol", "dave", "erin"]
    assert client.posted == {"bob": ssm_key("b" * 20 + "=="), "erin": ssm_key("e" * 20 + "==")}
    erin = store.get("erin")
    assert erin["admin"] is True and erin["ts_auth_key"] == "ts-key" and erin["warp_ipv6"] == "2606::1/128"
    assert store.get("dave")["disabled"] is True and store.get("bob")["warp_key"] is None


@pytest.mark.parametrize(
    "lines,error",
    [
        ([HEADER + ",extra", BOB + ","], "row 1: unknown column 'extra'"),
        ([HEADER.replace(",warp_ipv6", ""), BOB[:-1]], "row 1: missing column 'warp_ipv6'"),
        ([HEADER + ",name", BOB + ",x"], "row 1: repeated column 'name'"),
        ([HEADER, BOB.replace("bob", "-bob")], "row 2: bad username '-bob'"),
        ([HEADER, BOB.replace("b" * 20, "b" * 19)], "row 2: bad PSK"),
        ([HEADER, BOB.replace(",,false", ",tomorrow,false")], "row 2: bad Expiry 'tomorrow'"),
        ([HEADER, BOB.replace("false", "yes", 1)], "row 2: bad admin 'yes', use true or false"),
        ([HEADER, BOB, BOB.replace("bob,", "bobby,")], "row 3: PSK repeats row 2"),
        ([HEADER, BOB, BOB.replace("b" * 20, "c" * 20)], "row 3: name 'bob' repeats row 2"),
        ([HEADER, BOB.replace("bob", "alice")], "row 2: name 'alice' already exists"),
        ([HEADER, BOB.replace("bob,", "bobby,").replace("b" * 20, "a" * 20)], "row 2: PSK already exists"),
        ([HEADER, BOB + ","], "row 2: wrong number of cells, expected 8"),
    ],
)
def test_import_rejects_whole_file(client, lines, error):
    r = _import(client, *lines, f"zed,{'z' * 20}==,false,,false,,,")
    assert r.status_code == 400
    assert error in r.json()["detail"]
    assert _store_names(client) == ["alice"] and client.posted == {}


def test_import_reports_every_bad_row(client):
    r = _import(client, HEADER, BOB.replace("bob", "-x"), BOB, BOB.replace("bob", "alice").replace("b" * 20, "c" * 20))
    assert r.json()["detail"] == ["row 2: bad username '-x'", "row 3: PSK repeats row 2", "row 4: name 'alice' already exists"]


def test_import_needs_admin(client):
    assert _import(client, HEADER, BOB, headers={}).status_code == 401


def test_import_keeps_zone_and_defaults_utc(client, frozen):
    _import(client, HEADER, BOB.replace(",,false", ",2027-01-01T00:00,false"))
    assert store.get("bob")["expires_at"] == "2027-01-01T00:00:00+00:00"


def test_import_html_redirects_to_stats(client):
    r = _import(client, HEADER, BOB, headers=HTML)
    assert r.status_code == 303 and r.headers["location"] == "/ssm/server/v1/users"


def test_dashboard_has_import_form(client, monkeypatch):
    async def stats():
        return []

    monkeypatch.setattr(ssm, "get_stats", stats)
    text = client.get("/ssm/server/v1/users", headers=HTML).text
    assert 'action="/ssm/import"' in text and 'enctype="multipart/form-data"' in text


# --- users.json conversion (ADR 0006) ---------------------------------------

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "users_json_to_csv.py")
# The retired example-users.json: optional keys left out, as hand-written files have them.
OLD_USERS = {
    "users": [
        {
            "name": "user1",
            "password": "exampleuser1key00000==",
            "admin": False,
            "expires_at": "2026-10-08T12:00:00+00:00",
            "warp_key": "wireguard-private-key-for-user1=",
            "warp_ipv6": "2606:4700:110:8000::1/128",
        },
        {"name": "user2", "password": "exampleadminkey00000==", "admin": True},
        {"name": "user3", "password": "exampleuser3key00000==", "admin": False, "ts_auth_key": "ts-auth-key-for-user3"},
        {"name": "user4", "password": "exampleuser4key00000==", "disabled": True},
    ]
}


def test_users_json_round_trips_through_import_and_export(client, tmp_path):
    path = tmp_path / "users.json"
    path.write_text(json.dumps(OLD_USERS))
    converted = subprocess.run([sys.executable, "-I", SCRIPT, str(path)], capture_output=True, text=True, check=True).stdout
    store.delete("alice")
    r = client.post("/ssm/import", files={"file": ("users.csv", converted, "text/csv")}, headers=JSON)
    assert r.json() == {"added": ["user1", "user2", "user3", "user4"]}
    assert client.get("/ssm/export", headers=ADMIN).text == converted
    assert converted.splitlines()[1:] == [
        "user1,exampleuser1key00000==,false,2026-10-08T12:00:00+00:00,false,,wireguard-private-key-for-user1=,2606:4700:110:8000::1/128",
        "user2,exampleadminkey00000==,true,,false,,,",
        "user3,exampleuser3key00000==,false,,false,ts-auth-key-for-user3,,",
        "user4,exampleuser4key00000==,false,,true,,,",
    ]


def test_example_users_csv_imports(client):
    path = os.path.join(os.path.dirname(__file__), "..", "..", "example-users.csv")
    with open(path) as f:
        r = client.post("/ssm/import", files={"file": ("users.csv", f.read(), "text/csv")}, headers=JSON)
    assert r.status_code == 200, r.text


# --- WARP key ---------------------------------------------------------------

WG_KEY = base64.b64encode(bytes(range(32))).decode()


def _set_warp(client, key, ipv6, username="alice", headers=JSON, **kw):
    return client.post("/ssm/warp", data={"username": username, "warp_key": key, "warp_ipv6": ipv6}, headers=headers, **kw)


def _profile_has_warp(monkeypatch, name="alice"):
    """The user's next Profile config, with a WARP rule set (r6) asked for."""
    from app import utils

    monkeypatch.setattr(utils, "APP_CLIENT_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "scaffolds", "client"))
    monkeypatch.setattr(utils.Checker, "_verify_user", lambda self: None)
    monkeypatch.setattr(utils, "fetch_user_rules", lambda url: {"domain_suffix": ["ip6only.me"]})
    config = utils.Reader(
        username=name, psk=store.get(name)["password"], log_level="warn",
        dns_host="1.1.1.1", dns_sni="", dns_path="/", dns_detour="shadowsocks-uot",
        dns_final="dns-remote", dns_resolver="1.1.1.1", rules_v6_url="https://x/r6.json",
    ).unwarp()
    return "warp-ep" in json.dumps(config)


def test_set_warp_reaches_next_profile_config(client, monkeypatch):
    r = _set_warp(client, WG_KEY, "2606:4700:110:8000::1")
    assert r.status_code == 200, r.text
    assert r.json() == {"username": "alice", "warp_key": WG_KEY, "warp_ipv6": "2606:4700:110:8000::1/128"}
    assert _profile_has_warp(monkeypatch)


def test_clear_warp_drops_it_from_next_profile_config(client, monkeypatch):
    store.update("alice", warp_key=WG_KEY, warp_ipv6="2606:4700::1/128")
    r = _set_warp(client, "", "")
    assert r.json() == {"username": "alice", "warp_key": None, "warp_ipv6": None}
    assert not _profile_has_warp(monkeypatch)


@pytest.mark.parametrize(
    "key,ipv6,field",
    [
        (WG_KEY, "", "warp_ipv6"),  # both or neither
        ("", "2606:4700::1", "warp_key"),
        ("not base64!", "2606:4700::1", "warp_key"),
        (base64.b64encode(bytes(31)).decode(), "2606:4700::1", "warp_key"),
        (base64.b64encode(bytes(33)).decode(), "2606:4700::1", "warp_key"),
        (WG_KEY, "172.16.0.2", "warp_ipv6"),
        (WG_KEY, "not-an-address", "warp_ipv6"),
        (WG_KEY, "2606:4700::1/64", "warp_ipv6"),
        (WG_KEY, "fe80::1%eth0", "warp_ipv6"),
    ],
)
def test_set_warp_bad_value_is_400_and_keeps_old_key(client, key, ipv6, field):
    store.update("alice", warp_key=WG_KEY, warp_ipv6="2606:4700::1/128")
    r = _set_warp(client, key, ipv6)
    assert r.status_code == 400 and field in r.text
    entry = _entry(client, "alice")
    assert (entry["warp_key"], entry["warp_ipv6"]) == (WG_KEY, "2606:4700::1/128")


def test_set_warp_unknown_is_404(client):
    assert _set_warp(client, WG_KEY, "2606:4700::1", username="ghost").status_code == 404


def test_set_warp_needs_admin_and_allows_admin_entries(client):
    _add_entry(client, "root", admin=True)
    assert client.post("/ssm/warp", data={"username": "root", "warp_key": WG_KEY, "warp_ipv6": "2606:4700::1"}).status_code == 401
    assert _set_warp(client, WG_KEY, "2606:4700::1", username="root").status_code == 200


def test_set_warp_html_redirects_to_stats(client):
    r = _set_warp(client, WG_KEY, "2606:4700::1", headers=HTML, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/ssm/server/v1/users"


def test_stats_page_shows_prefilled_warp_form(client, monkeypatch):
    store.update("alice", warp_key=WG_KEY, warp_ipv6="2606:4700::1/128")
    _add_entry(client, "bob")

    async def stats():
        return [{"username": "alice"}, {"username": "bob"}, {"username": "stranger"}]

    monkeypatch.setattr(ssm, "get_stats", stats)
    json_rows = client.get("/ssm/server/v1/users", headers=JSON).json()["users"]
    assert all("warp_key" not in r for r in json_rows)  # stats JSON unchanged
    html = client.get("/ssm/server/v1/users", headers=HTML).text
    assert '<th class="more">Keys</th>' in html
    assert html.count('action="/ssm/warp"') == 2  # alice, bob; not stranger (no User record)
    assert f'value="{WG_KEY}"' in html and 'value="2606:4700::1/128"' in html
    assert "—" in html
