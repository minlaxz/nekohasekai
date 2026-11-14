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
from app import ssm_api  # noqa: E402
from app.routes import ssm  # noqa: E402
from app.utils import ssm_key  # noqa: E402

ADMIN = {"Authorization": "Basic " + base64.b64encode(b"admin:secret").decode()}
JSON = {**ADMIN, "Accept": "application/json"}
HTML = {**ADMIN, "Accept": "text/html,*/*;q=0.8"}


@pytest.fixture
def client(monkeypatch, user_store, fake_ssm):
    store.add(name="alice", password="a" * 20 + "==")
    monkeypatch.setattr(ssm, "APP_HOST", "vpn.example")
    monkeypatch.setenv("APP_ADMIN_PASSWORD", "secret")
    monkeypatch.delenv("APP_ADMIN_USER", raising=False)

    fake_ssm.users["alice"] = {"username": "alice", "uPSK": ssm_key("a" * 20 + "==")}
    c = TestClient(app)
    c.ssm = fake_ssm
    return c


def _store_names(client):
    return [u["name"] for u in store.records()]


# --- auth -------------------------------------------------------------------


def test_no_credentials_is_401(client):
    assert client.post("/ssm/create", data={"username": "bob"}).status_code == 401
    assert client.get("/ssm/form").status_code == 401


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
    assert "bob" in client.ssm.users and "bob" in _store_names(client)
    # ssm-api gets the SS-2022 key; the file and the user keep `k` (#24)
    assert client.ssm.users["bob"]["uPSK"] == ssm_key(body["uPSK"])
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
    assert name not in client.ssm.users


@pytest.mark.parametrize("name", ["HP_HM", "kma-km-ios", "r1", "x" * 32])
def test_create_accepts_existing_name_shapes(client, name):
    assert client.post("/ssm/create", data={"username": name}, headers=JSON).status_code == 200


def test_create_with_ssm_api_down_is_502(client, monkeypatch):
    async def down(username, upsk):
        raise ssm_api.SsmUnavailable("ssm-api is down")

    monkeypatch.setattr(client.ssm, "add_user", down)
    assert client.post("/ssm/create", data={"username": "bob"}, headers=JSON).status_code == 502
    assert _store_names(client) == ["alice"]  # so the admin can create bob again


# --- delete -----------------------------------------------------------------


def test_delete(client):
    r = client.post("/ssm/delete", data={"username": "alice"}, headers=JSON)
    assert r.status_code == 200
    assert r.json() == {"deleted": "alice"}
    assert "alice" not in client.ssm.users and _store_names(client) == []


def test_delete_unknown_is_404(client):
    assert client.post("/ssm/delete", data={"username": "ghost"}, headers=JSON).status_code == 404


# --- stats ------------------------------------------------------------------


def test_stats_json(client, monkeypatch):
    client.ssm.stats_rows = [{"username": "alice", "downlinkBytes": 1}]
    r = client.get("/ssm/server/v1/users", headers=JSON)
    assert r.json() == {"users": [{
        "username": "alice", "downlinkBytes": 1, "uPSK": ssm_key("a" * 20 + "=="), "downlinkBytesHuman": "1 B",
        "expires_at": None, "expired": False, "disabled": False, "last_fetch": None,
    }]}
    r = client.get("/ssm/server/v1/users", headers=HTML)
    assert r.headers["content-type"].startswith("text/html")


def test_last_fetch_kept_in_user_record(client, monkeypatch, frozen):
    import app.main as main
    from fastapi import HTTPException

    def verify_user(username, psk):
        if psk != "good":
            raise HTTPException(status_code=403, detail="bad PSK")

    monkeypatch.setattr(main, "verify_user", verify_user)
    monkeypatch.setattr(main, "load_template", dict)
    monkeypatch.setattr(main, "build_profile", lambda template, user, **_: {})
    client.ssm.stats_rows = [{"username": "alice", "downlinkBytes": 0}]
    assert not hasattr(ssm, "LAST_FETCH")

    def last_fetch():
        return store.get("alice")["last_fetch"]

    assert client.get("/c?j=alice&k=bad&dp=/q").status_code == 403
    assert client.get("/i?j=alice&k=good").status_code == 200
    assert last_fetch() is None
    assert client.get("/c?j=alice&k=good&dp=/q").status_code == 200
    assert last_fetch() == frozen.isoformat()
    assert ssm._ago(frozen.isoformat()) == "just now" and ssm._ago(None) == "never"

    # Restart: the stats page reads it back from the database, not process memory.
    rows = TestClient(app).get("/ssm/server/v1/users", headers=JSON).json()["users"]
    assert rows[0]["last_fetch"] == frozen.isoformat()

    assert client.post("/ssm/delete", data={"username": "alice"}, headers=JSON).status_code == 200
    assert client.post("/ssm/create", data={"username": "alice"}, headers=JSON).status_code == 200
    assert last_fetch() is None


# --- expiry -----------------------------------------------------------------


def _entry(client, name):
    return store.get(name)


def _set_expiry(client, name, expires_at):
    store.update(name, expires_at=expires_at)


def _add_entry(client, name, **extra):
    store.add(name=name, password=name[0] * 20 + "==", **extra)


def test_create_html_shows_expiry(client, frozen):
    r = client.post("/ssm/create", data={"username": "bob", "months": 1}, headers=HTML)
    assert "2026-11-08T12:00:00+00:00" in r.text


@pytest.mark.parametrize("months", [-1, 7, "x"])
def test_create_months_out_of_range_is_400(client, months):
    r = client.post("/ssm/create", data={"username": "bob", "months": months}, headers=JSON)
    assert r.status_code == 400
    assert "bob" not in client.ssm.users


def test_renew_expired_counts_from_now(client, frozen):
    _set_expiry(client, "alice", "2026-09-01T00:00:00+00:00")
    client.ssm.users.pop("alice")
    r = client.post("/ssm/renew", data={"username": "alice", "months": 1}, headers=JSON)
    assert r.status_code == 200, r.text
    assert r.json() == {"username": "alice", "expires_at": "2026-11-05T12:00:00+00:00"}
    assert "alice" in client.ssm.users
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

    client.ssm.stats_rows = [{"username": "alice", "downlinkBytes": 1}]
    rows = client.get("/ssm/server/v1/users", headers=JSON).json()["users"]
    assert rows == [
        {"username": "alice", "downlinkBytes": 1, "uPSK": ssm_key("a" * 20 + "=="), "downlinkBytesHuman": "1 B",
         "expires_at": "2026-12-01T00:00:00+00:00", "expired": False, "disabled": False, "last_fetch": None},
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
    assert "alice" not in client.ssm.users


def test_set_expiry_empty_means_never_and_restores(client, frozen):
    _set_expiry(client, "alice", "2026-01-01T00:00:00+00:00")
    client.ssm.users.pop("alice")
    r = client.post("/ssm/expiry", data={"username": "alice", "expires_at": ""}, headers=JSON)
    assert r.json() == {"username": "alice", "expires_at": None}
    assert _entry(client, "alice")["expires_at"] is None and "alice" in client.ssm.users


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


def test_disable_removes_user_and_keeps_expiry(client, frozen):
    _set_expiry(client, "alice", "2026-12-01T00:00:00+00:00")
    r = client.post("/ssm/disable", data={"username": "alice"}, headers=JSON)
    assert r.status_code == 200, r.text
    assert r.json() == {"username": "alice", "disabled": True}
    assert "alice" not in client.ssm.users
    assert _entry(client, "alice")["disabled"] is True
    assert _entry(client, "alice")["expires_at"] == "2026-12-01T00:00:00+00:00"
    # idempotent
    assert client.post("/ssm/disable", data={"username": "alice"}, headers=JSON).status_code == 200


def test_enable_restores_user(client, frozen):
    client.post("/ssm/disable", data={"username": "alice"}, headers=JSON)
    r = client.post("/ssm/enable", data={"username": "alice"}, headers=JSON)
    assert r.json() == {"username": "alice", "disabled": False}
    assert "alice" in client.ssm.users and _entry(client, "alice")["disabled"] is False
    assert client.post("/ssm/enable", data={"username": "alice"}, headers=JSON).status_code == 200


def test_enable_expired_user_stays_out(client, frozen):
    _set_expiry(client, "alice", "2026-01-01T00:00:00+00:00")
    client.post("/ssm/disable", data={"username": "alice"}, headers=JSON)
    client.post("/ssm/enable", data={"username": "alice"}, headers=JSON)
    assert "alice" not in client.ssm.users


def test_set_expiry_does_not_enable(client, frozen):
    client.post("/ssm/disable", data={"username": "alice"}, headers=JSON)
    client.post("/ssm/expiry", data={"username": "alice", "expires_at": ""}, headers=JSON)
    assert "alice" not in client.ssm.users and _entry(client, "alice")["disabled"] is True


def test_renew_does_not_enable(client, frozen):
    client.post("/ssm/disable", data={"username": "alice"}, headers=JSON)
    client.post("/ssm/renew", data={"username": "alice", "months": 1}, headers=JSON)
    assert "alice" not in client.ssm.users and _entry(client, "alice")["disabled"] is True


@pytest.mark.parametrize("path", ["/ssm/disable", "/ssm/enable"])
def test_disable_enable_unknown_or_memory_only_is_404(client, path):
    client.ssm.users["stranger"] = {"username": "stranger"}
    assert client.post(path, data={"username": "ghost"}, headers=JSON).status_code == 404
    assert client.post(path, data={"username": "stranger"}, headers=JSON).status_code == 404


@pytest.mark.parametrize("path", ["/ssm/disable", "/ssm/delete"])
def test_admin_entry_is_403(client, path):
    _add_entry(client, "root", admin=True)
    client.ssm.users["root"] = {"username": "root"}
    assert client.post(path, data={"username": "root"}, headers=JSON).status_code == 403
    assert "root" in client.ssm.users and "root" in _store_names(client)


@pytest.mark.parametrize("path", ["/ssm/disable", "/ssm/enable", "/ssm/delete"])
def test_disable_enable_delete_html_redirects_to_stats(client, frozen, path):
    r = client.post(path, data={"username": "alice"}, headers=HTML, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/ssm/server/v1/users"


def test_stats_lists_disabled_users_with_buttons(client, monkeypatch, frozen):
    _add_entry(client, "bob", disabled=True)
    _add_entry(client, "root", admin=True)

    client.ssm.stats_rows = [{"username": "alice"}, {"username": "root"}, {"username": "stranger"}]
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


# --- domain error bodies ------------------------------------------------------


def _bad_field_body(field, msg):
    detail = {"loc": ["body", field], "msg": msg, "type": "value_error.invalid"}
    return {"message": f"1 validation error:\n  {detail!r}"}


@pytest.mark.parametrize(
    "path,data,status,body",
    [
        ("/ssm/renew", {"username": "ghost", "months": 1}, 404,
         {"message": "The resource you are looking for is not found."}),
        ("/ssm/create", {"username": "alice"}, 409, {"detail": "User 'alice' already exists"}),
        ("/ssm/disable", {"username": "root"}, 403, {"detail": "User 'root' is an admin entry"}),
        ("/ssm/expiry", {"username": "alice", "expires_at": "tomorrow"}, 400,
         _bad_field_body("expires_at", "must be ISO 8601, e.g. 2026-12-31T00:00 (UTC when no zone is given)")),
        ("/ssm/mesh", {"username": "alice", "ts_auth_key": "a b"}, 400,
         _bad_field_body("ts_auth_key", "must not contain whitespace")),
    ],
)
def test_lifecycle_errors_keep_their_http_bodies(client, path, data, status, body):
    _add_entry(client, "root", admin=True)
    r = client.post(path, data=data, headers=JSON)
    assert (r.status_code, r.json()) == (status, body)


def test_import_rejected_keeps_its_http_body(client):
    r = client.post("/ssm/import", files={"file": ("u.csv", "name,password\n")}, headers=JSON)
    assert r.status_code == 400
    assert r.json() == {"detail": [f"row 1: missing column '{c}'" for c in ssm.CSV_FIELDS[2:]]}


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
    client.ssm.stats_rows = []
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
        f"erin,{'e' * 20}==,true,2027-01-01T00:00:00+00:00,false,ts-key,{WG_KEY},2606::1",  # a bare address is stored as /128
    )
    assert r.status_code == 200
    assert r.json() == {"added": ["bob", "carol", "dave", "erin"]}
    assert _store_names(client) == ["alice", "bob", "carol", "dave", "erin"]
    assert {n: u["uPSK"] for n, u in client.ssm.users.items() if n != "alice"} == {
        "bob": ssm_key("b" * 20 + "=="), "erin": ssm_key("e" * 20 + "==")
    }
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
    assert _store_names(client) == ["alice"] and set(client.ssm.users) == {"alice"}


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
    client.ssm.stats_rows = []
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
            "warp_key": "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=",
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
        "user1,exampleuser1key00000==,false,2026-10-08T12:00:00+00:00,false,,AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=,2606:4700:110:8000::1/128",
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


def _profile(**kwargs):
    """alice's next Profile config, built from her User record and the real Client template."""
    from app import utils

    return utils.build_profile(
        utils.load_template(os.path.join(os.path.dirname(__file__), "..", "..", "scaffolds", "client")),
        store.get("alice"),
        username="alice", psk="a" * 20 + "==", log_level="warn",
        dns_host="1.1.1.1", dns_sni="", dns_path="/", dns_detour="shadowsocks-uot",
        dns_final="dns-remote", dns_resolver="1.1.1.1", **kwargs,
    )


def _profile_has_warp():
    """Whether alice's next Profile config, with a WARP rule set (r6) asked for, has WARP on."""
    config = _profile(rules_v6_url="https://x/r6.json", fetch_rules=lambda url: {"domain_suffix": ["ip6only.me"]})
    return "warp-ep" in json.dumps(config)


def test_set_warp_reaches_next_profile_config(client):
    r = _set_warp(client, WG_KEY, "2606:4700:110:8000::1")
    assert r.status_code == 200, r.text
    assert r.json() == {"username": "alice", "warp_key": WG_KEY, "warp_ipv6": "2606:4700:110:8000::1/128"}
    assert _profile_has_warp()


def test_clear_warp_drops_it_from_next_profile_config(client):
    store.update("alice", warp_key=WG_KEY, warp_ipv6="2606:4700::1/128")
    r = _set_warp(client, "", "")
    assert r.json() == {"username": "alice", "warp_key": None, "warp_ipv6": None}
    assert not _profile_has_warp()


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


@pytest.mark.parametrize(
    "key,ipv6,error",
    [
        (WG_KEY, "", "row 2: bad warp_ipv6: set both warp_key and warp_ipv6, or neither"),
        ("", "2606:4700::1/128", "row 2: bad warp_key: set both warp_key and warp_ipv6, or neither"),
        ("wk=", "2606:4700::1/128", "row 2: bad warp_key: must be a WireGuard private key: base64 of 32 bytes"),
        (WG_KEY, "2606:4700::1/64", "row 2: bad warp_ipv6: must be an IPv6 address, bare or /128"),
    ],
)
def test_import_rejects_a_warp_key_that_set_warp_rejects(client, key, ipv6, error):
    r = _import(client, HEADER, BOB[:-1] + f"{key},{ipv6}")
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == [error]
    assert _store_names(client) == ["alice"] and set(client.ssm.users) == {"alice"}


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

    client.ssm.stats_rows = [{"username": "alice"}, {"username": "bob"}, {"username": "stranger"}]
    json_rows = client.get("/ssm/server/v1/users", headers=JSON).json()["users"]
    assert all("warp_key" not in r for r in json_rows)  # stats JSON unchanged
    html = client.get("/ssm/server/v1/users", headers=HTML).text
    assert '<th class="more">Keys</th>' in html
    assert html.count('action="/ssm/warp"') == 2  # alice, bob; not stranger (no User record)
    assert f'value="{WG_KEY}"' in html and 'value="2606:4700::1/128"' in html
    assert "—" in html


# --- Mesh key ---------------------------------------------------------------


def _set_mesh(client, key, username="alice", headers=JSON, **kw):
    return client.post("/ssm/mesh", data={"username": username, "ts_auth_key": key}, headers=headers, **kw)


def _profile_has_mesh():
    """Whether alice's next Profile config joins the Mesh (ts-ep, its route rule and DNS server)."""
    return "ts-ep" in json.dumps(_profile(control_url="https://hs.example"))


def test_set_mesh_reaches_next_profile_config(client):
    r = _set_mesh(client, "  test-mesh-key  ")
    assert r.status_code == 200, r.text
    assert r.json() == {"username": "alice", "ts_auth_key": "test-mesh-key"}
    assert _profile_has_mesh()


def test_clear_mesh_drops_it_from_next_profile_config(client):
    store.update("alice", ts_auth_key="test-mesh-key")
    r = _set_mesh(client, "  ")
    assert r.json() == {"username": "alice", "ts_auth_key": None}
    assert not _profile_has_mesh()


@pytest.mark.parametrize("key", ["hskey auth", "hskey\tauth", "a\nb"])
def test_set_mesh_inner_whitespace_is_400_and_keeps_old_key(client, key):
    store.update("alice", ts_auth_key="test-mesh-key")
    r = _set_mesh(client, key)
    assert r.status_code == 400 and "ts_auth_key" in r.text
    assert _entry(client, "alice")["ts_auth_key"] == "test-mesh-key"


def test_set_mesh_unknown_is_404(client):
    assert _set_mesh(client, "test-mesh-key", username="ghost").status_code == 404


def test_set_mesh_needs_admin_and_allows_admin_entries(client):
    _add_entry(client, "root", admin=True)
    assert client.post("/ssm/mesh", data={"username": "root", "ts_auth_key": "k"}).status_code == 401
    assert _set_mesh(client, "k", username="root").status_code == 200


def test_set_mesh_html_redirects_to_stats(client):
    r = _set_mesh(client, "k", headers=HTML, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/ssm/server/v1/users"


def test_stats_page_shows_mesh_form_above_warp_form(client, monkeypatch):
    store.update("alice", ts_auth_key="test-mesh-key")
    _add_entry(client, "bob")

    client.ssm.stats_rows = [{"username": "alice"}, {"username": "bob"}, {"username": "stranger"}]
    json_rows = client.get("/ssm/server/v1/users", headers=JSON).json()["users"]
    assert all("ts_auth_key" not in r for r in json_rows)  # stats JSON unchanged
    html = client.get("/ssm/server/v1/users", headers=HTML).text
    assert html.count('action="/ssm/mesh"') == 2  # alice, bob; not stranger (no User record)
    assert 'value="test-mesh-key"' in html
    assert html.index('action="/ssm/mesh"') < html.index('action="/ssm/warp"')
    assert "—" in html
