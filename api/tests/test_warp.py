import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.utils import apply_warp, apply_warp_rules, strip_tun_ipv6  # noqa: E402

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
    assert ep["detour"] == "shadowsocks-uot"
    assert any(r.get("ip_version") == 6 and r.get("outbound") == "warp-ep" for r in route["rules"])
    assert any("domain_suffix" in r and r["server"] == "dns-remote" for r in dns["rules"])


def test_without_key_strips_endpoint_and_rules():
    route, dns = _load("route"), _load("dns")
    eps = apply_warp(_load("endpoints"), route, dns, "", "")
    assert all(e["tag"] != "warp-ep" for e in eps)
    assert "warp-ep" not in json.dumps(route)
    # Without WARP no domain may get AAAA answers: no rule before the AAAA block.
    assert dns["rules"][0] == {"query_type": ["AAAA"], "action": "predefined", "rcode": "NOERROR"}


def test_r6_fills_route_and_dns_rules():
    route, dns = _load("route"), _load("dns")
    apply_warp_rules(route, dns, {"domain_suffix": ["ip6only.me"], "domain_keyword": ["ipv6"]})
    r = next(r for r in route["rules"] if r.get("outbound") == "warp-ep" and "domain_suffix" in r)
    d = next(r for r in dns["rules"] if "domain_suffix" in r)
    assert r["domain_suffix"] == d["domain_suffix"] == ["ip6only.me"]
    assert r["domain_keyword"] == d["domain_keyword"] == ["ipv6"]


def test_no_r6_strips_empty_domain_rules():
    route, dns = _load("route"), _load("dns")
    apply_warp_rules(route, dns, {})
    # An empty rule would match everything: both must go, the IPv6 rule stays.
    assert not any(r.get("outbound") == "warp-ep" and "domain_suffix" in r for r in route["rules"])
    assert not any("domain_suffix" in r for r in dns["rules"])
    assert any(r.get("ip_version") == 6 for r in route["rules"])


def test_dns_has_no_legacy_strategy():
    # sing-box 1.14 deprecates the DNS rule action `strategy`; AAAA is blocked by a
    # query_type rule instead, and the global `strategy` would override the r6 rule.
    dns = _load("dns")
    assert "strategy" not in dns
    assert not any("strategy" in r for r in dns["rules"])
    r6 = next(i for i, r in enumerate(dns["rules"]) if "domain_suffix" in r)
    aaaa = next(i for i, r in enumerate(dns["rules"]) if r.get("query_type") == ["AAAA"])
    assert r6 < aaaa


def test_strip_tun_ipv6_keeps_ipv4_only():
    inbounds = _load("inbounds")
    strip_tun_ipv6(inbounds)
    tun = next(i for i in inbounds if i["type"] == "tun")
    assert tun["address"] == ["10.10.10.1/30"]
