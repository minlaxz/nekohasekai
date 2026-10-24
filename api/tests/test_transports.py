import json
import os
import sys

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
    assert obs["Proxy"]["outbounds"] == ["shadowsocks-uot"]
    assert obs["All"]["outbounds"] == ["direct", "shadowsocks-uot"]
    assert [t for t, o in obs.items() if o["type"] == "shadowsocks"] == ["shadowsocks-uot"]
    assert obs["shadowsocks-uot"]["detour"] == "shadowtls"
    assert obs["shadowsocks-uot"]["udp_over_tcp"] == {"enabled": True, "version": 2}
    assert obs["shadowsocks-uot"]["password"] == "server-psk:mP0JOjQ94DITPUE5SARMFA=="
    assert obs["shadowtls"]["password"] == "shared-pw"
    for ob in obs.values():
        assert all(tag in obs for tag in ob.get("outbounds", []))
        if "detour" in ob:
            assert ob["detour"] in obs
