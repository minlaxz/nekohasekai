"""SS-2022 key derivation (#24): users keep their `k`; ssm-api and the client get the derived key."""

import base64
import csv
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import utils  # noqa: E402
from app.utils import client_key, ssm_key  # noqa: E402

CLIENT = os.path.join(os.path.dirname(__file__), "..", "..", "scaffolds", "client")
K = "nj75pm4nlaslo8xm8xtK=="


def test_derives_from_k():
    assert ssm_key(K) == "nj75pm4nlaslo8xm8xtKnj75"


def test_client_key_is_sha256_of_ssm_key_cut_to_16_bytes():
    # what sing-box's server makes of the 18-byte ssm_key; its client needs exactly these 16 bytes
    assert client_key(K) == "+sA1Rl+PHSeeDd8nD0MlIg=="
    assert len(base64.b64decode(client_key(K))) == 16


@pytest.mark.parametrize(
    "bad",
    [
        "insecure-user123==",  # an old example-users.json shape: `-` is not base64, too short
        "a" * 24,  # native 16-byte key: not the `k` format
        "a" * 20,  # no `==`
        "a" * 19 + "!==",  # outside the base64 alphabet
        "",
    ],
)
def test_rejects_non_k(bad):
    with pytest.raises(ValueError, match="PSK"):
        ssm_key(bad)


def _outbounds(tmp_path, monkeypatch):
    """Profile config outbounds from a Client template that Init has filled with the server PSK."""
    with open(os.path.join(CLIENT, "outbounds.json")) as f:
        template = json.load(f)
    for ob in template["outbounds"]:
        if ob["type"] == "shadowsocks":
            ob["password"] = "server-psk"
        elif ob["tag"] == "shadowtls":
            ob["password"] = "shared-pw"
    (tmp_path / "outbounds.json").write_text(json.dumps(template))
    monkeypatch.setattr(utils, "APP_CLIENT_DIR", str(tmp_path))
    reader = utils.Reader.__new__(utils.Reader)  # skip the ssm-api PSK check
    reader.psk = K
    return {o["tag"]: o for o in reader._outbounds()}


def test_profile_outbounds_carry_server_and_derived_key(tmp_path, monkeypatch):
    obs = _outbounds(tmp_path, monkeypatch)
    ss = obs["shadowsocks-uot"]
    assert ss["method"] == "2022-blake3-aes-128-gcm"
    assert ss["password"] == "server-psk:+sA1Rl+PHSeeDd8nD0MlIg=="


def test_profile_uses_shadowtls_only(tmp_path, monkeypatch):
    obs = _outbounds(tmp_path, monkeypatch)
    assert "hysteria2" not in obs and "shadowsocks-hy2" not in obs
    assert "Proxy" not in obs and "All" not in obs
    assert {t for t, ob in obs.items() if ob["type"] in ("urltest", "selector")} == {
        "All Outbounds", "Remote DNS Detour"
    }
    assert obs["All Outbounds"]["type"] == "urltest"
    assert obs["All Outbounds"]["outbounds"] == ["direct", "shadowsocks-uot"]
    assert obs["Remote DNS Detour"]["outbounds"] == ["direct", "shadowsocks-uot"]
    assert obs["Remote DNS Detour"]["default"] == "direct"
    assert obs["Remote DNS Detour"]["interrupt_exist_connections"] is True
    assert [t for t, o in obs.items() if o["type"] == "shadowsocks"] == ["shadowsocks-uot"]
    assert obs["shadowsocks-uot"]["detour"] == "shadowtls"
    assert obs["shadowsocks-uot"]["udp_over_tcp"] == {"enabled": True, "version": 2}
    assert obs["shadowtls"]["password"] == "shared-pw"  # shared, not the user's key
    for ob in obs.values():
        assert all(tag in obs for tag in ob.get("outbounds", []))
        if "detour" in ob:
            assert ob["detour"] in obs


@pytest.mark.parametrize("with_endpoints", [False, True])
def test_profile_references_existing_outbounds_and_keeps_proxy_detours(monkeypatch, user_store, with_endpoints):
    monkeypatch.setattr(utils, "APP_CLIENT_DIR", CLIENT)
    monkeypatch.setattr(utils.Checker, "_verify_user", lambda self: None)
    user = {"admin": True}
    if with_endpoints:
        user.update(ts_auth_key="ts-key", warp_key="wg-key", warp_ipv6="2606:4700::1/128")
    user_store.add(name="alice", password="a" * 20 + "==", **user)
    monkeypatch.setattr(utils, "APP_TS_CONTROL_URL", "https://hs.example")
    reader = utils.Reader(
        username="alice", psk="a" * 20 + "==", log_level="warn",
        dns_host="1.1.1.1", dns_sni="", dns_path="/", dns_detour="shadowsocks-uot",
        dns_final="dns-remote", dns_resolver="1.1.1.1",
        rules_v6_url="https://x/r6.json",
    )
    monkeypatch.setattr(utils, "fetch_user_rules", lambda url: {"domain_suffix": ["ip6only.me"]})
    config = reader.unwarp()
    tags = {ob["tag"] for ob in config["outbounds"] + config.get("endpoints", [])}

    def check_references(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in ("detour", "outbound"):
                    assert child in tags
                    assert child not in ("Proxy", "All")
                check_references(child)
        elif isinstance(value, list):
            for child in value:
                check_references(child)

    check_references(config)
    resolver = next(s for s in config["dns"]["servers"] if s["tag"] == "dns-resolver")
    assert resolver["detour"] == "shadowsocks-uot"
    assert next(h for h in config["http_clients"] if h["tag"] == "proxy")["detour"] == "shadowsocks-uot"
    full = next(r for r in config["route"]["rules"] if r.get("clash_mode") == "Full")
    assert full["outbound"] == "shadowsocks-uot"
    assert all(ep["detour"] == "shadowsocks-uot" for ep in config.get("endpoints", []))
    # Mesh and WARP keys come from the User record
    assert {ep["tag"] for ep in config.get("endpoints", [])} == ({"ts-ep", "warp-ep"} if with_endpoints else set())


@pytest.mark.parametrize("warp_key,r6,warp_on", [("wg-key", "https://x/r6.json", True), ("wg-key", "", False), ("", "https://x/r6.json", False)])
def test_warp_needs_key_and_warp_rule_set(monkeypatch, user_store, warp_key, r6, warp_on):
    monkeypatch.setattr(utils, "APP_CLIENT_DIR", CLIENT)
    monkeypatch.setattr(utils.Checker, "_verify_user", lambda self: None)
    user_store.add(name="alice", password="a" * 20 + "==", warp_key=warp_key, warp_ipv6="2606:4700::1/128")
    fetched = []
    monkeypatch.setattr(utils, "fetch_user_rules", lambda url: fetched.append(url) or {"domain_suffix": ["ip6only.me"]})
    config = utils.Reader(
        username="alice", psk="a" * 20 + "==", log_level="warn",
        dns_host="1.1.1.1", dns_sni="", dns_path="/", dns_detour="shadowsocks-uot",
        dns_final="dns-remote", dns_resolver="1.1.1.1", rules_v6_url=r6,
    ).unwarp()
    assert ("warp-ep" in json.dumps(config)) is warp_on
    assert fetched == ([r6] if warp_on else [])


class _Resp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def test_verify_compares_derived_key(monkeypatch):
    monkeypatch.setattr(utils.httpx, "get", lambda url, timeout: _Resp({"uPSK": ssm_key(K)}))
    utils.Checker("alice", K)  # no raise


@pytest.mark.parametrize("reported", [K, "nj75pm4nlaslo8xm8xtKnj76", ""])
def test_verify_rejects_other_keys(monkeypatch, reported):
    monkeypatch.setattr(utils.httpx, "get", lambda url, timeout: _Resp({"uPSK": reported}))
    with pytest.raises(utils.HTTPException):
        utils.Checker("alice", K)


def test_example_users_have_valid_k():
    path = os.path.join(os.path.dirname(__file__), "..", "..", "example-users.csv")
    with open(path) as f:
        for u in csv.DictReader(f):
            ssm_key(u["password"])
