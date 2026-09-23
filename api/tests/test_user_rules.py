import json
import os
import sys

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.utils import apply_user_rules, fetch_user_rules, parse_user_rules  # noqa: E402

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


def test_apply_extends_exactly_the_tcp_and_udp_rules():
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
        walk(rule)
    want = {"domain_suffix": ["gstatic.com", "x.com"], "domain_keyword": ["google"]}
    assert hits == [want, want]


def test_apply_without_target_list_is_500():
    with pytest.raises(HTTPException) as exc:
        apply_user_rules({"rules": [{"outbound": "TCP", "clash_mode": "Full"}]}, {"domain_suffix": ["x.com"]})
    assert exc.value.status_code == 500
