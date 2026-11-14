import asyncio
import os
import sys

import httpx
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import ssm_api  # noqa: E402


def test_http_ssm_maps_404_and_failures(monkeypatch):
    def ssm(request):
        path = request.url.path
        if path == "/server/v1/users/ghost":
            return httpx.Response(404)
        if path == "/server/v1/users/alice":
            return httpx.Response(200, json={"username": "alice", "uPSK": "key"})
        if path == "/server/v1/users" and request.method == "GET":
            return httpx.Response(200, json={"users": [{"username": "alice"}]})
        return httpx.Response(500)

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(ssm), **kw))
    s = ssm_api.HttpSsm("http://ssm")

    assert asyncio.run(s.get_user("alice")) == {"username": "alice", "uPSK": "key"}
    assert asyncio.run(s.get_user("ghost")) is None
    asyncio.run(s.remove_user("ghost"))  # idempotent: no raise
    assert asyncio.run(s.list_users()) == [{"username": "alice"}]
    with pytest.raises(ssm_api.SsmUnavailable):
        asyncio.run(s.add_user("bob", "key"))  # 500
    with pytest.raises(ssm_api.SsmUnavailable):
        asyncio.run(s.stats())
