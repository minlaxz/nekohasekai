import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import main  # noqa: E402


@pytest.fixture
def seen(monkeypatch, user_store):
    """build_profile kwargs of the last `/c` request."""
    user_store.add(name="alice", password="a" * 20 + "==")
    seen = {}

    def build_profile(template, user, **kwargs):
        seen.clear()
        seen.update(kwargs)
        return {}

    monkeypatch.setattr(main, "verify_user", lambda j, k: None)
    monkeypatch.setattr(main, "load_template", dict)
    monkeypatch.setattr(main, "build_profile", build_profile)
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


def test_rr_ip_cidr_is_the_user_ip_list(seen):
    assert get("rr.ip_cidr=1.2.3.4,1.2.3.5").status_code == 200
    assert seen["user_ips"] == "1.2.3.4,1.2.3.5"


def test_rr_ip_cidr_repeated_params_combine(seen):
    assert get("rr.ip_cidr=1.2.3.4&rr.ip_cidr=1.2.3.5").status_code == 200
    assert seen["user_ips"] == "1.2.3.4,1.2.3.5"


def test_rr_ip_cidr_absent_or_empty_means_no_ips(seen):
    assert get("").status_code == 200
    assert seen["user_ips"] == ""
    assert get("rr.ip_cidr=").status_code == 200
    assert seen["user_ips"] == ""


@pytest.mark.parametrize("query", ["rr.port=443", "rr.ip_cdir=1.2.3.4"])
def test_unknown_rr_param_fails_loudly(seen, query):
    r = get(query)
    assert r.status_code == 400
    assert query.split("=")[0] in r.text
    assert not seen


def test_dv_is_gone_and_ignored(seen):
    assert get("dv=6").status_code == 200
    assert "dns_version" not in seen
