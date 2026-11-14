import asyncio
from datetime import datetime, timezone

import pytest

from app import lifecycle, store


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
