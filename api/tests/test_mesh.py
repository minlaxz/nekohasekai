import copy
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.utils import apply_mesh  # noqa: E402

CLIENT = os.path.join(os.path.dirname(__file__), "..", "..", "scaffolds", "client")


def _load(name):
    with open(os.path.join(CLIENT, f"{name}.json")) as f:
        return json.load(f)[name]


def test_with_key_fills_endpoint():
    route = _load("route")
    eps = apply_mesh(_load("endpoints"), route, "alice", "tskey-x", "https://hs.example")
    ep = next(e for e in eps if e["tag"] == "ts-ep")
    assert ep["auth_key"] == "tskey-x"
    assert ep["hostname"] == "alice"
    assert ep["control_url"] == "https://hs.example"
    assert any(r.get("outbound") == "ts-ep" for r in route["rules"])


def test_without_key_strips_endpoint_and_rules():
    route = _load("route")
    before = copy.deepcopy(route["rules"])
    eps = apply_mesh(_load("endpoints"), route, "bob", "", "")
    assert eps == []
    assert all(r.get("outbound") != "ts-ep" for r in route["rules"])
    assert len(route["rules"]) == len(before) - 1


def test_full_mode_admin_only():
    from app.utils import apply_full_mode

    route = _load("route")
    n = len(route["rules"])
    apply_full_mode(route, admin=True)
    assert len(route["rules"]) == n
    apply_full_mode(route, admin=False)
    assert all(r.get("clash_mode") != "Full" for r in route["rules"])
    assert len(route["rules"]) == n - 2
