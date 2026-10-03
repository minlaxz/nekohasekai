"""SS-2022 key derivation (#24): users keep their `k`; ssm-api and the client get the derived key."""

import base64
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
        "insecure-user123==",  # old example-users.json shape: `-` is not base64, too short
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
    (tmp_path / "outbounds.json").write_text(json.dumps(template))
    monkeypatch.setattr(utils, "APP_CLIENT_DIR", str(tmp_path))
    reader = utils.Reader.__new__(utils.Reader)  # skip the ssm-api PSK check
    reader.psk = K
    return {o["tag"]: o for o in reader._outbounds()}


def test_profile_outbounds_carry_server_and_derived_key(tmp_path, monkeypatch):
    obs = _outbounds(tmp_path, monkeypatch)
    for tag in ("shadowsocks-uot", "shadowsocks-hy2"):
        assert obs[tag]["method"] == "2022-blake3-aes-128-gcm"
        assert obs[tag]["password"] == "server-psk:+sA1Rl+PHSeeDd8nD0MlIg=="


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
    path = os.path.join(os.path.dirname(__file__), "..", "..", "example-users.json")
    with open(path) as f:
        for u in json.load(f)["users"]:
            ssm_key(u["password"])
