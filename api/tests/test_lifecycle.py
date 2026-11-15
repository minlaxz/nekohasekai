import asyncio
import base64
import re
from datetime import datetime, timezone

import pytest

from app import lifecycle, ssm_api, store
from app.utils import ssm_key


@pytest.fixture
def ssm(user_store, fake_ssm):
    """alice: a live Managed user, in the store and in ssm-api."""
    store.add(name="alice", password="a" * 20 + "==")
    fake_ssm.users["alice"] = {"username": "alice"}
    return fake_ssm


def _add(name, **extra):
    store.add(name=name, password=name[0] * 20 + "==", **extra)


# --- Reconcile ------------------------------------------------------------------


def test_reconcile_posts_derived_keys_and_skips_bad_entries(ssm):
    store.add(name="bad", password="insecure-user123==")
    store.add(name="bob", password="nj75pm4nlaslo8xm8xtK==")
    asyncio.run(lifecycle.reconcile())
    assert ssm.users["bob"] == {"username": "bob", "uPSK": "nj75pm4nlaslo8xm8xtKnj75"}
    assert "bad" not in ssm.users


def test_reconcile_removes_expired_and_adds_live(ssm, frozen):
    store.update("alice", expires_at="2026-10-05T11:59:00+00:00")  # expired, still in ssm-api
    _add("carol", expires_at="2026-12-01T00:00:00+00:00")  # live, missing from ssm-api
    _add("dan")  # no Expiry: never expires
    _add("eve", expires_at="2026-01-01")  # hand-edited, no zone: still expired
    ssm.users["stranger"] = {"username": "stranger"}  # in ssm-api only: left alone
    asyncio.run(lifecycle.reconcile())
    assert set(ssm.users) == {"carol", "dan", "stranger"}
    assert [u["name"] for u in store.records()] == ["alice", "carol", "dan", "eve"]


def test_reconcile_keeps_disabled_users_out(ssm, frozen):
    _add("bob", disabled=True)
    ssm.users["bob"] = {"username": "bob"}
    _add("carol", disabled=True, expires_at="2026-01-01T00:00:00+00:00")
    _add("dan", disabled=False)
    asyncio.run(lifecycle.reconcile())
    assert set(ssm.users) == {"alice", "dan"}


# --- Expiry helpers -------------------------------------------------------------


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
    assert lifecycle.add_months(dt, months).date().isoformat() == end


@pytest.mark.parametrize(
    "fields,expired,out",
    [
        ({}, False, False),  # no Expiry: never expires
        ({"expires_at": "2026-10-05T12:00:00+00:00"}, True, True),  # Expiry is the first instant out
        ({"expires_at": "2026-10-05T12:00:01+00:00"}, False, False),
        ({"expires_at": "2026-10-05T11:00:00"}, True, True),  # no zone = UTC
        ({"expires_at": "2026-10-05T14:00:00+09:00"}, True, True),  # zone kept: 05:00 UTC
        ({"disabled": True}, False, True),
        ({"disabled": True, "expires_at": "2026-01-01T00:00:00+00:00"}, True, True),
    ],
)
def test_expired_and_out(frozen, fields, expired, out):
    entry = {"name": "bob", "expires_at": None, "disabled": False, **fields}  # as the store gives it
    assert (lifecycle.is_expired(entry, frozen), lifecycle.is_out(entry, frozen)) == (expired, out)


# --- Last fetch -----------------------------------------------------------------


def test_record_fetch_stores_now(ssm, frozen):
    lifecycle.record_fetch("alice")
    assert store.get("alice")["last_fetch"] == "2026-10-05T12:00:00+00:00"


def test_record_fetch_for_a_user_with_no_record_is_a_no_op(ssm, frozen):
    lifecycle.record_fetch("stranger")
    assert store.get("stranger") is None


# --- Create ---------------------------------------------------------------------


def test_create_returns_the_record_and_adds_the_ssm_key(ssm, frozen):
    entry = asyncio.run(lifecycle.create("bob", 0))
    psk = entry["password"]
    assert re.fullmatch(r"[a-z0-9]{20}==", psk)
    assert entry["name"] == "bob" and store.get("bob") == entry
    # ssm-api gets the SS-2022 key; the user keeps the PSK (#24)
    assert ssm.users["bob"]["uPSK"] == ssm_key(psk)


@pytest.mark.parametrize(
    "months,expires_at",
    [(0, "2026-10-08T12:00:00+00:00"), (3, "2027-01-08T12:00:00+00:00")],  # months plus the 3-day Trial period
)
def test_create_sets_expiry(ssm, frozen, months, expires_at):
    assert asyncio.run(lifecycle.create("bob", months))["expires_at"] == expires_at


def test_create_existing_user_raises_user_exists(ssm):
    ssm.users["stranger"] = {"username": "stranger"}  # in ssm-api only
    for name in ("alice", "stranger"):
        with pytest.raises(lifecycle.UserExists):
            asyncio.run(lifecycle.create(name, 0))
    assert [u["name"] for u in store.records()] == ["alice"]


def test_create_with_ssm_api_down_leaves_no_user_record(ssm, monkeypatch):
    async def down(username, upsk):
        raise ssm_api.SsmUnavailable("ssm-api is down")

    monkeypatch.setattr(ssm, "add_user", down)
    with pytest.raises(ssm_api.SsmUnavailable):
        asyncio.run(lifecycle.create("bob", 0))
    assert store.get("bob") is None  # so the admin can create bob again


def test_create_that_fails_at_the_store_leaves_nobody_in_ssm_api(ssm, monkeypatch):
    monkeypatch.setattr(lifecycle, "new_psk", lambda: "a" * 20 + "==")  # alice's PSK: the store refuses it
    with pytest.raises(Exception):
        asyncio.run(lifecycle.create("bob", 0))
    assert "bob" not in ssm.users and store.get("bob") is None


# --- Delete ---------------------------------------------------------------------


def test_delete_removes_the_user_from_ssm_api_and_the_store(ssm):
    asyncio.run(lifecycle.delete("alice"))
    assert "alice" not in ssm.users and store.get("alice") is None


def test_delete_user_only_in_ssm_api(ssm):
    ssm.users["stranger"] = {"username": "stranger"}
    asyncio.run(lifecycle.delete("stranger"))
    assert "stranger" not in ssm.users and store.get("alice") is not None


def test_delete_unknown_raises_user_not_found(ssm):
    with pytest.raises(lifecycle.UserNotFound):
        asyncio.run(lifecycle.delete("ghost"))


@pytest.mark.parametrize("in_ssm_api", [True, False])
def test_delete_admin_entry_raises_admin_entry(ssm, in_ssm_api):
    _add("root", admin=True)
    if in_ssm_api:
        ssm.users["root"] = {"username": "root"}
    with pytest.raises(lifecycle.AdminEntry):
        asyncio.run(lifecycle.delete("root"))
    assert store.get("root") is not None and ("root" in ssm.users) == in_ssm_api


def test_delete_with_ssm_api_down_keeps_the_record(ssm):
    ssm.down = True
    with pytest.raises(ssm_api.SsmUnavailable):
        asyncio.run(lifecycle.delete("alice"))
    assert store.get("alice") is not None


# --- Renewal --------------------------------------------------------------------


@pytest.mark.parametrize(
    "expires_at,months,renewed",
    [
        ("2026-10-20T00:00:00+00:00", 2, "2026-12-20T00:00:00+00:00"),  # live: from the current Expiry
        ("2026-09-01T00:00:00+00:00", 1, "2026-11-05T12:00:00+00:00"),  # Expired: from now
        (None, 1, "2026-11-05T12:00:00+00:00"),  # no Expiry: from now, no Trial period
        ("2027-01-31T00:00:00+00:00", 1, "2027-02-28T00:00:00+00:00"),  # day clamped
    ],
)
def test_renew_pushes_expiry_by_calendar_months(ssm, frozen, expires_at, months, renewed):
    store.update("alice", expires_at=expires_at)
    entry = asyncio.run(lifecycle.renew("alice", months))
    assert entry["expires_at"] == renewed and store.get("alice") == entry


def test_renew_brings_an_expired_user_back_with_the_same_psk(ssm, frozen):
    store.update("alice", expires_at="2026-09-01T00:00:00+00:00")
    ssm.users.pop("alice")
    asyncio.run(lifecycle.renew("alice", 1))
    assert ssm.users["alice"]["uPSK"] == ssm_key("a" * 20 + "==")


def test_renew_does_not_enable(ssm, frozen):
    store.update("alice", disabled=True)
    entry = asyncio.run(lifecycle.renew("alice", 1))
    assert entry["disabled"] is True and "alice" not in ssm.users


# --- Setting Expiry -------------------------------------------------------------


@pytest.mark.parametrize(
    "value,stored",
    [
        ("2027-01-01T09:00:00+09:00", "2027-01-01T09:00:00+09:00"),  # zone kept
        (" 2027-01-01T00:00 ", "2027-01-01T00:00:00+00:00"),  # no zone = UTC
        ("", None),  # never
    ],
)
def test_set_expiry_stores_the_instant(ssm, value, stored):
    entry = asyncio.run(lifecycle.set_expiry("alice", value))
    assert entry["expires_at"] == stored and store.get("alice") == entry


def test_set_expiry_unparsable_raises_invalid_field(ssm):
    with pytest.raises(lifecycle.InvalidField) as exc:
        asyncio.run(lifecycle.set_expiry("alice", "tomorrow"))
    assert exc.value.field == "expires_at"
    assert exc.value.msg == "must be ISO 8601, e.g. 2026-12-31T00:00 (UTC when no zone is given)"
    assert store.get("alice")["expires_at"] is None


def test_set_expiry_past_removes_the_user_and_future_or_empty_puts_them_back(ssm, frozen):
    asyncio.run(lifecycle.set_expiry("alice", "2026-01-01T00:00"))
    assert "alice" not in ssm.users
    asyncio.run(lifecycle.set_expiry("alice", "2027-01-01T00:00"))
    assert "alice" in ssm.users
    asyncio.run(lifecycle.set_expiry("alice", "2026-01-01T00:00"))
    asyncio.run(lifecycle.set_expiry("alice", ""))
    assert "alice" in ssm.users


def test_set_expiry_does_not_enable(ssm, frozen):
    store.update("alice", disabled=True)
    asyncio.run(lifecycle.set_expiry("alice", ""))
    assert "alice" not in ssm.users


# --- Disable and enable ---------------------------------------------------------


def test_disable_takes_the_user_out_and_keeps_the_record(ssm, frozen):
    store.update("alice", expires_at="2026-12-01T00:00:00+00:00")
    entry = asyncio.run(lifecycle.disable("alice"))
    assert entry["disabled"] is True and store.get("alice") == entry
    assert (entry["password"], entry["expires_at"]) == ("a" * 20 + "==", "2026-12-01T00:00:00+00:00")
    assert "alice" not in ssm.users
    assert asyncio.run(lifecycle.disable("alice")) == entry  # repeat: no-op


def test_disable_admin_entry_raises_admin_entry(ssm):
    _add("root", admin=True)
    ssm.users["root"] = {"username": "root"}
    with pytest.raises(lifecycle.AdminEntry):
        asyncio.run(lifecycle.disable("root"))
    assert store.get("root")["disabled"] is False and "root" in ssm.users


def test_enable_puts_the_user_back_with_the_same_psk(ssm, frozen):
    asyncio.run(lifecycle.disable("alice"))
    entry = asyncio.run(lifecycle.enable("alice"))
    assert entry["disabled"] is False and store.get("alice") == entry
    assert ssm.users["alice"]["uPSK"] == ssm_key("a" * 20 + "==")
    assert asyncio.run(lifecycle.enable("alice")) == entry  # repeat: no-op


def test_enable_an_expired_user_keeps_them_out(ssm, frozen):
    store.update("alice", disabled=True, expires_at="2026-01-01T00:00:00+00:00")
    asyncio.run(lifecycle.enable("alice"))
    assert "alice" not in ssm.users


# --- User not found -------------------------------------------------------------


CHANGES = [
    lambda name: lifecycle.renew(name, 1),
    lambda name: lifecycle.set_expiry(name, ""),
    lifecycle.disable,
    lifecycle.enable,
]


@pytest.mark.parametrize("change", CHANGES)
def test_change_to_a_missing_user_raises_user_not_found(ssm, change):
    ssm.users["stranger"] = {"username": "stranger"}  # in ssm-api only: still not found
    for name in ("ghost", "stranger"):
        with pytest.raises(lifecycle.UserNotFound):
            asyncio.run(change(name))


@pytest.mark.parametrize("change", CHANGES)
def test_change_to_a_user_deleted_meanwhile_raises_user_not_found(ssm, monkeypatch, change):
    stale = store.get("alice")
    store.delete("alice")
    monkeypatch.setattr(store, "get", lambda name: stale)  # read before the delete
    with pytest.raises(lifecycle.UserNotFound):
        asyncio.run(change("alice"))


# --- WARP key and Mesh key ------------------------------------------------------
# Neither affects access: no Reconcile.

WG_KEY = base64.b64encode(bytes(range(32))).decode()


def test_set_warp_stores_the_key_with_a_128_address(ssm):
    entry = lifecycle.set_warp_key("alice", f" {WG_KEY} ", " 2606:4700:110:8000::1 ")
    assert (entry["warp_key"], entry["warp_ipv6"]) == (WG_KEY, "2606:4700:110:8000::1/128")
    assert store.get("alice")["warp_ipv6"] == "2606:4700:110:8000::1/128"


def test_set_warp_both_empty_clears_it(ssm):
    store.update("alice", warp_key=WG_KEY, warp_ipv6="2606:4700::1/128")
    entry = lifecycle.set_warp_key("alice", "", " ")
    assert (entry["warp_key"], entry["warp_ipv6"]) == (None, None)


@pytest.mark.parametrize(
    "key,ipv6,field,msg",
    [
        (WG_KEY, "", "warp_ipv6", "set both warp_key and warp_ipv6, or neither"),
        ("", "2606:4700::1", "warp_key", "set both warp_key and warp_ipv6, or neither"),
        ("not base64!", "2606:4700::1", "warp_key", "must be a WireGuard private key: base64 of 32 bytes"),
        (base64.b64encode(bytes(31)).decode(), "2606:4700::1", "warp_key", "must be a WireGuard private key: base64 of 32 bytes"),
        (base64.b64encode(bytes(33)).decode(), "2606:4700::1", "warp_key", "must be a WireGuard private key: base64 of 32 bytes"),
        (WG_KEY, "172.16.0.2", "warp_ipv6", "must be an IPv6 address, bare or /128"),
        (WG_KEY, "not-an-address", "warp_ipv6", "must be an IPv6 address, bare or /128"),
        (WG_KEY, "2606:4700::1/64", "warp_ipv6", "must be an IPv6 address, bare or /128"),
        (WG_KEY, "fe80::1%eth0", "warp_ipv6", "must be an IPv6 address, bare or /128"),
    ],
)
def test_set_warp_bad_value_raises_invalid_field_and_keeps_the_old_key(ssm, key, ipv6, field, msg):
    store.update("alice", warp_key=WG_KEY, warp_ipv6="2606:4700::1/128")
    with pytest.raises(lifecycle.InvalidField) as exc:
        lifecycle.set_warp_key("alice", key, ipv6)
    assert (exc.value.field, exc.value.msg) == (field, msg)
    assert (store.get("alice")["warp_key"], store.get("alice")["warp_ipv6"]) == (WG_KEY, "2606:4700::1/128")


def test_parse_warp_key_returns_the_stored_form_without_a_user():  # User import reuses it
    assert lifecycle.parse_warp_key(WG_KEY, "2606:4700::1/128") == (WG_KEY, "2606:4700::1/128")
    assert lifecycle.parse_warp_key("", "") == (None, None)


def test_set_mesh_trims_the_key_and_empty_clears_it(ssm):
    assert lifecycle.set_mesh_key("alice", "  test-mesh-key  ")["ts_auth_key"] == "test-mesh-key"
    assert store.get("alice")["ts_auth_key"] == "test-mesh-key"
    assert lifecycle.set_mesh_key("alice", "  ")["ts_auth_key"] is None


@pytest.mark.parametrize("key", ["hskey auth", "hskey\tauth", "a\nb"])
def test_set_mesh_inner_whitespace_raises_invalid_field_and_keeps_the_old_key(ssm, key):
    store.update("alice", ts_auth_key="test-mesh-key")
    with pytest.raises(lifecycle.InvalidField) as exc:
        lifecycle.set_mesh_key("alice", key)
    assert (exc.value.field, exc.value.msg) == ("ts_auth_key", "must not contain whitespace")
    assert store.get("alice")["ts_auth_key"] == "test-mesh-key"


KEY_CHANGES = [
    lambda name: lifecycle.set_warp_key(name, WG_KEY, "2606:4700::1"),
    lambda name: lifecycle.set_mesh_key(name, "test-mesh-key"),
]


@pytest.mark.parametrize("change", KEY_CHANGES)
def test_key_change_allowed_on_admin_entries_and_leaves_ssm_api_alone(ssm, change):
    _add("root", admin=True)
    _add("bob", expires_at="2026-01-01T00:00:00+00:00")  # Expired, still in ssm-api: no Reconcile
    ssm.users["bob"] = {"username": "bob"}
    assert change("root")["name"] == "root"
    change("bob")
    assert set(ssm.users) == {"alice", "bob"}


@pytest.mark.parametrize("change", KEY_CHANGES)
def test_key_change_to_a_missing_user_raises_user_not_found(ssm, change):
    ssm.users["stranger"] = {"username": "stranger"}  # in ssm-api only: still not found
    for name in ("ghost", "stranger"):
        with pytest.raises(lifecycle.UserNotFound):
            change(name)


# --- User import and User export ------------------------------------------------

HEADER = ",".join(lifecycle.CSV_FIELDS)
BOB = f"bob,{'b' * 20}==,false,,false,,,"


def _import(*lines):
    return asyncio.run(lifecycle.import_csv("\n".join(lines) + "\n"))


def _rejected(*lines):
    with pytest.raises(lifecycle.ImportRejected) as exc:
        _import(*lines)
    return exc.value.errors


def test_import_adds_every_row_and_live_ones_reach_ssm_api(ssm, frozen):
    added = _import(
        HEADER,
        BOB,
        f"carol,{'c' * 20}==,false,2026-01-01T00:00:00+00:00,false,,,",  # Expired
        f"dave,{'d' * 20}==,false,,true,,,",  # Disabled
        f"erin,{'e' * 20}==,true,2027-01-01T00:00:00+00:00,false,ts-key,{WG_KEY},2606::1",  # bare address stored as /128
    )
    assert added == ["bob", "carol", "dave", "erin"]
    assert [u["name"] for u in store.records()] == ["alice", "bob", "carol", "dave", "erin"]
    assert {n: u["uPSK"] for n, u in ssm.users.items() if n != "alice"} == {
        "bob": ssm_key("b" * 20 + "=="), "erin": ssm_key("e" * 20 + "==")
    }
    erin = store.get("erin")
    assert erin is not None and erin["admin"] is True and erin["ts_auth_key"] == "ts-key" and erin["warp_ipv6"] == "2606::1/128"
    assert store.get("dave")["disabled"] is True and store.get("bob")["warp_key"] is None  # type: ignore[index]


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
        ([HEADER, f"bob,{'b' * 20}==,false,,maybe,,,"], "row 2: bad disabled 'maybe', use true or false"),
        ([HEADER, BOB, BOB.replace("bob,", "bobby,")], "row 3: PSK repeats row 2"),
        ([HEADER, BOB, BOB.replace("b" * 20, "c" * 20)], "row 3: name 'bob' repeats row 2"),
        ([HEADER, BOB.replace("bob", "alice")], "row 2: name 'alice' already exists"),
        ([HEADER, BOB.replace("bob,", "bobby,").replace("b" * 20, "a" * 20)], "row 2: PSK already exists"),
        ([HEADER, BOB + ","], "row 2: wrong number of cells, expected 8"),
        ([HEADER, BOB[:-1] + f"{WG_KEY},"], "row 2: bad warp_ipv6: set both warp_key and warp_ipv6, or neither"),
        ([HEADER, BOB[:-1] + ",2606:4700::1/128"], "row 2: bad warp_key: set both warp_key and warp_ipv6, or neither"),
        ([HEADER, BOB[:-1] + "wk=,2606:4700::1/128"], "row 2: bad warp_key: must be a WireGuard private key: base64 of 32 bytes"),
        ([HEADER, BOB[:-1] + f"{WG_KEY},2606:4700::1/64"], "row 2: bad warp_ipv6: must be an IPv6 address, bare or /128"),
    ],
)
def test_import_rejects_the_whole_file(ssm, lines, error):
    assert error in _rejected(*lines, f"zed,{'z' * 20}==,false,,false,,,")
    assert [u["name"] for u in store.records()] == ["alice"] and set(ssm.users) == {"alice"}


def test_import_reports_every_bad_row_and_never_echoes_a_psk(ssm):
    errors = _rejected(HEADER, BOB.replace("bob", "-x"), BOB, BOB.replace("bob", "alice").replace("b" * 20, "c" * 20), BOB.replace("bob,", "bo,").replace("b" * 20, "x" * 19))
    assert errors == [
        "row 2: bad username '-x'",
        "row 3: PSK repeats row 2",
        "row 4: name 'alice' already exists",
        "row 5: bad PSK",
    ]
    assert not any("x" * 19 in e or "b" * 20 in e for e in errors)


def test_import_keeps_zone_and_defaults_utc(ssm):
    _import(HEADER, BOB.replace(",,false", ",2027-01-01T00:00,false"), f"carol,{'c' * 20}==,,2027-01-01T09:00+09:00,,,,")
    assert store.get("bob")["expires_at"] == "2027-01-01T00:00:00+00:00"  # type: ignore[index]
    carol = store.get("carol")
    assert carol is not None and carol["expires_at"] == "2027-01-01T09:00:00+09:00"
    assert (carol["admin"], carol["disabled"]) == (False, False)  # empty flags = false


def test_export_writes_every_record_without_last_fetch(ssm):
    _add("bob", expires_at="2026-10-08T12:00:00+00:00", disabled=True, warp_key="wk=", warp_ipv6="2606::1/128")
    _add("root", admin=True, ts_auth_key="ts-key")
    store.update("alice", last_fetch="2026-10-01T00:00:00+00:00")
    assert lifecycle.export_csv().splitlines() == [
        "name,password,admin,expires_at,disabled,ts_auth_key,warp_key,warp_ipv6",
        f"alice,{'a' * 20}==,false,,false,,,",
        f"bob,{'b' * 20}==,false,2026-10-08T12:00:00+00:00,true,,wk=,2606::1/128",
        f"root,{'r' * 20}==,true,,false,ts-key,,",
    ]


def test_export_then_import_round_trips(ssm):
    _add("bob", expires_at="2026-10-08T12:00:00+00:00", disabled=True, warp_key=WG_KEY, warp_ipv6="2606::1/128")
    _add("root", admin=True, ts_auth_key="ts-key")
    exported = lifecycle.export_csv()
    for u in store.records():
        store.delete(u["name"])
    assert asyncio.run(lifecycle.import_csv(exported)) == ["alice", "bob", "root"]
    assert lifecycle.export_csv() == exported
