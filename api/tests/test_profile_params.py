import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import main  # noqa: E402


@pytest.fixture
def seen(monkeypatch, user_store):
    """Reader kwargs of the last `/c` request."""
    user_store.add(name="alice", password="a" * 20 + "==")
    seen = {}

    class FakeReader:
        def __init__(self, **kwargs):
            seen.clear()
            seen.update(kwargs)

        def unwarp(self):
            return {}

    monkeypatch.setattr(main, "Reader", FakeReader)
    return seen


def get(query):
    return TestClient(main.app).get(f"/c?j=alice&k=good&dp=/q&{query}")


def test_r4_is_the_user_rule_set(seen):
    assert get("r4=https://x/r.json&r6=https://x/r6.json").status_code == 200
    assert seen["rules_url"] == "https://x/r.json"
    assert seen["rules_v6_url"] == "https://x/r6.json"


def test_old_r_fails_loudly(seen):
    r = get("r=https://x/r.json")
    assert r.status_code == 400
    assert "r4" in r.text
    assert not seen


def test_dv_is_gone_and_ignored(seen):
    assert get("dv=6").status_code == 200
    assert "dns_version" not in seen
