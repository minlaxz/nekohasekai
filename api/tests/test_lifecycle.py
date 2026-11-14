import asyncio
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
