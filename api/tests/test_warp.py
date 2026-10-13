import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.utils import apply_warp  # noqa: E402

CLIENT = os.path.join(os.path.dirname(__file__), "..", "..", "scaffolds", "client")


def _load(name):
    with open(os.path.join(CLIENT, f"{name}.json")) as f:
        return json.load(f)[name]


def test_with_key_fills_endpoint():
    route, dns = _load("route"), _load("dns")
    eps = apply_warp(_load("endpoints"), route, dns, "wg-key", "2606:4700::1/128")
    ep = next(e for e in eps if e["tag"] == "warp-ep")
    assert ep["private_key"] == "wg-key"
    assert ep["address"] == ["172.16.0.2/32", "2606:4700::1/128"]
    assert ep["detour"] == "Proxy"
    assert any(r.get("ip_version") == 6 and r.get("outbound") == "warp-ep" for r in route["rules"])
    assert any(r.get("strategy") == "prefer_ipv4" for r in dns["rules"])


def test_without_key_strips_endpoint_and_rules():
    route, dns = _load("route"), _load("dns")
    eps = apply_warp(_load("endpoints"), route, dns, "", "")
    assert all(e["tag"] != "warp-ep" for e in eps)
    assert "warp-ep" not in json.dumps(route)
    # Without WARP no domain may get AAAA answers.
    assert "prefer_ipv4" not in json.dumps(dns)
