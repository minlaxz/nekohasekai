import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import utils  # noqa: E402

CLIENT = os.path.join(os.path.dirname(__file__), "..", "..", "scaffolds", "client")


def _outbounds(tmp_path, monkeypatch):
    """Profile config outbounds, built from a Client template that Init has filled in."""
    with open(os.path.join(CLIENT, "outbounds.json")) as f:
        template = json.load(f)
    shadowtls = next(o for o in template["outbounds"] if o["tag"] == "shadowtls")
    shadowtls.update(server="1.2.3.4", server_port=8896, password="shared-pw")
    for o in template["outbounds"]:
        if o["type"] == "shadowsocks":
            o["password"] = "server-psk"
    (tmp_path / "outbounds.json").write_text(json.dumps(template))
    monkeypatch.setattr(utils, "APP_CLIENT_DIR", str(tmp_path))

    reader = utils.Reader.__new__(utils.Reader)  # skip the ssm-api PSK check
    reader.psk = "a" * 20 + "=="
    return {o["tag"]: o for o in reader._outbounds()}


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
    assert obs["shadowsocks-uot"]["password"] == "server-psk:mP0JOjQ94DITPUE5SARMFA=="
    assert obs["shadowtls"]["password"] == "shared-pw"
    for ob in obs.values():
        assert all(tag in obs for tag in ob.get("outbounds", []))
        if "detour" in ob:
            assert ob["detour"] in obs


@pytest.mark.parametrize("with_endpoints", [False, True])
def test_profile_references_existing_outbounds_and_keeps_proxy_detours(monkeypatch, with_endpoints):
    monkeypatch.setattr(utils, "APP_CLIENT_DIR", CLIENT)
    monkeypatch.setattr(utils.Checker, "_verify_user", lambda self: None)
    user = {"admin": True}
    if with_endpoints:
        user.update(ts_auth_key="ts-key", warp_key="wg-key", warp_ipv6="2606:4700::1/128")
    monkeypatch.setattr(utils, "user_entry", lambda username: user)
    monkeypatch.setattr(utils, "APP_TS_CONTROL_URL", "https://hs.example")
    reader = utils.Reader(
        username="alice", psk="a" * 20 + "==", log_level="warn",
        dns_host="1.1.1.1", dns_sni="", dns_path="/", dns_detour="shadowsocks-uot",
        dns_final="dns-remote", dns_resolver="1.1.1.1", dns_version=6,
    )
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
