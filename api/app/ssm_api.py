"""The one seam to ssm-api: list, read, add and remove Managed users, and read traffic stats.

Callers go through `client` only; tests replace it with an in-memory fake.
Values come back as ssm-api returns them; domain logic stays with the callers.
"""

import os
from typing import Any, Dict, List, Optional

import httpx

HTTP_TIMEOUT = 5  # seconds


class SsmUnavailable(Exception):
    """ssm-api could not be reached or refused the request."""


class HttpSsm:
    def __init__(self, url: str) -> None:
        self.url = url

    async def _request(self, method: str, path: str, json: Any = None, ok_404: bool = False) -> httpx.Response:
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
                r = await c.request(method, f"{self.url}/server/v1/{path}", json=json)
            if not (ok_404 and r.status_code == 404):
                r.raise_for_status()
        except httpx.HTTPError as exc:
            raise SsmUnavailable(str(exc)) from exc
        return r

    async def list_users(self) -> List[Dict[str, Any]]:
        return (await self._request("GET", "users")).json().get("users", [])

    async def get_user(self, username: str) -> Optional[Dict[str, Any]]:
        """The user, or None if ssm-api does not hold them."""
        r = await self._request("GET", f"users/{username}", ok_404=True)
        return None if r.status_code == 404 else r.json()

    async def add_user(self, username: str, upsk: str) -> None:
        await self._request("POST", "users", json={"username": username, "uPSK": upsk})

    async def remove_user(self, username: str) -> None:
        """Idempotent: a user ssm-api does not hold is not an error."""
        await self._request("DELETE", f"users/{username}", ok_404=True)

    async def stats(self) -> List[Dict[str, Any]]:
        return (await self._request("GET", "stats")).json()["users"]


client = HttpSsm(os.getenv("APP_INTERNAL_SSM_UPSTREAM", "http://sing-box:8888"))
