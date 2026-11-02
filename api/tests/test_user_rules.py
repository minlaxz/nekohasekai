import json
import os
import sys

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.utils import (  # noqa: E402
    apply_rules_detour,
    apply_user_rules,
    fetch_user_rules,
    parse_user_ips,
    parse_user_rules,
)

CLIENT = os.path.join(os.path.dirname(__file__), "..", "..", "scaffolds", "client")


def _route():
    with open(os.path.join(CLIENT, "route.json")) as f:
        return json.load(f)["route"]


def _body(rules, version=5):
    return json.dumps({"version": version, "rules": rules}).encode()


def test_parse_collects_matchers_by_field():
    body = _body(
        [
            {"domain_suffix": ["a.com", "b.com"], "domain_keyword": ["google"]},
            {"domain_suffix": ["c.com"], "domain_regex": [r"^cdn\d+\.x\.com$"]},
        ]
    )
    assert parse_user_rules(body) == {
        "domain_suffix": ["a.com", "b.com", "c.com"],
        "domain_keyword": ["google"],
        "domain_regex": [r"^cdn\d+\.x\.com$"],
    }


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        json.dumps({"rules": [{"domain_suffix": ["a.com"]}]}).encode(),
        _body([]),
        _body([{"domain_suffix": ["a.com"], "domain": ["b.com"]}]),
        _body([{"ip_cidr": ["1.1.1.1/32"]}]),
        _body([{"domain_suffix": "a.com"}]),
        _body([{"domain_keyword": "google"}]),
        _body([{}]),
    ],
)
def test_parse_rejects_bad_structure(body):
    with pytest.raises(HTTPException) as exc:
        parse_user_rules(body)
    assert exc.value.status_code == 400


@pytest.mark.parametrize(
    "url",
    [
        "http://gist.githubusercontent.com/x/raw/r.json",
        "https://sing-box:8888/server/v1/users",
        "https://gist.githubusercontent.com@evil.example/r.json",
    ],
)
def test_fetch_rejects_disallowed_urls_without_network(url):
    with pytest.raises(HTTPException) as exc:
        fetch_user_rules(url)
    assert exc.value.status_code == 400


def test_apply_extends_exactly_the_proxy_rule():
    route = _route()
    apply_user_rules(
        route,
        {"domain_suffix": ["x.com", "gstatic.com", "x.com"], "domain_keyword": ["google"]},
    )
    hits = []

    def walk(rule):
        if "domain_suffix" in rule:
            hits.append(rule)
        for child in rule.get("rules", []):
            walk(child)

    for rule in route["rules"]:
        if rule.get("outbound") == "shadowsocks-uot":
            walk(rule)
    want = {"domain_suffix": ["gstatic.com", "x.com"], "domain_keyword": ["google"]}
    assert hits == [want]


def test_user_ips_become_single_host_prefixes():
    assert parse_user_ips("1.2.3.4,1.2.3.5") == ["1.2.3.4/32", "1.2.3.5/32"]


@pytest.mark.parametrize(
    "raw",
    ["nope", "1.2.3.4/32", "1.2.3.0/24", "2001:db8::1", "1.2.3.4,,1.2.3.5", "1.2.3.4,", " 1.2.3.4", "1.2.3"],
)
def test_user_ips_reject_anything_but_a_bare_ipv4(raw):
    with pytest.raises(HTTPException) as exc:
        parse_user_ips(raw)
    assert exc.value.status_code == 400
    assert "rr.ip_cidr" in exc.value.detail


def test_user_ips_join_only_the_proxied_list():
    route = _route()
    apply_user_rules(route, {"ip_cidr": parse_user_ips("1.2.3.4,1.2.3.4")})
    proxied = route["rules"][-1]["rules"][0]["rules"][1]
    assert proxied == {"domain_suffix": ["gstatic.com"], "ip_cidr": ["1.2.3.4/32"]}
    assert route["rules"][0]["ip_cidr"] == ["100.64.0.0/10"]  # Mesh rule untouched


def test_apply_without_target_list_is_500():
    with pytest.raises(HTTPException) as exc:
        apply_user_rules({"rules": [{"outbound": "shadowsocks-uot", "clash_mode": "Full"}]}, {"domain_suffix": ["x.com"]})
    assert exc.value.status_code == 500


def test_apply_rules_detour_sets_the_default_http_client():
    route = _route()
    assert route["default_http_client"] == "proxy"
    assert not any("http_client" in rs for rs in route["rule_set"])  # all via default
    apply_rules_detour(route, "direct")
    assert route["default_http_client"] == "direct"
