import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import utils  # noqa: E402

CLIENT = os.path.join(os.path.dirname(__file__), "..", "..", "scaffolds", "client")
CERT = ["-----BEGIN CERTIFICATE-----", "abc", "-----END CERTIFICATE-----"]


def _outbounds(tmp_path, monkeypatch):
    """Profile config outbounds, built from a Client template that Init has filled in."""
    with open(os.path.join(CLIENT, "outbounds.json")) as f:
        template = json.load(f)
    hy2 = next(o for o in template["outbounds"] if o["tag"] == "hysteria2")
    hy2.update(server="1.2.3.4", server_port=8897, password="shared-pw")
    hy2["obfs"]["password"] = "obfs-pw"
    hy2["tls"].update(server_name="hysteria2.internal", certificate=CERT)
    for o in template["outbounds"]:
        if o["type"] == "shadowsocks":
            o["password"] = "server-psk"
    (tmp_path / "outbounds.json").write_text(json.dumps(template))
    monkeypatch.setattr(utils, "APP_CLIENT_DIR", str(tmp_path))

    reader = utils.Reader.__new__(utils.Reader)  # skip the ssm-api PSK check
    reader.psk = "a" * 20 + "=="
    return {o["tag"]: o for o in reader._outbounds()}


def test_shadowsocks_hy2_gets_psk_and_never_multiplex(tmp_path, monkeypatch):
    obs = _outbounds(tmp_path, monkeypatch)
    ss = obs["shadowsocks-hy2"]
    assert ss["password"] == "server-psk:mP0JOjQ94DITPUE5SARMFA=="
    assert ss["detour"] == "hysteria2"
    assert "multiplex" not in ss  # smux would move UDP off QUIC datagrams


def test_hysteria2_outbound_is_served_with_shared_secrets(tmp_path, monkeypatch):
    hy2 = _outbounds(tmp_path, monkeypatch)["hysteria2"]
    assert hy2["password"] == "shared-pw"  # not the user's PSK
    assert hy2["obfs"] == {"type": "salamander", "password": "obfs-pw"}
    assert hy2["tls"] == {"enabled": True, "server_name": "hysteria2.internal", "certificate": CERT}
    assert "up_mbps" not in hy2 and "down_mbps" not in hy2


def test_two_transports_only(tmp_path, monkeypatch):
    obs = _outbounds(tmp_path, monkeypatch)
    assert obs["Proxy"]["outbounds"] == ["shadowsocks-uot", "shadowsocks-hy2"]
    assert [t for t, o in obs.items() if o["type"] == "shadowsocks"] == ["shadowsocks-uot", "shadowsocks-hy2"]
    assert obs["shadowsocks-uot"]["password"] == "server-psk:mP0JOjQ94DITPUE5SARMFA=="
