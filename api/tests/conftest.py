import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import ssm_api, store  # noqa: E402


class InMemorySsm:
    """ssm-api for tests. Seed `users` and `stats_rows`; set `down` to make every call fail."""

    def __init__(self):
        self.users = {}  # username -> {"username", "uPSK"}, as ssm-api lists them
        self.stats_rows = []
        self.down = False

    def _check(self):
        if self.down:
            raise ssm_api.SsmUnavailable("ssm-api is down")

    async def list_users(self):
        self._check()
        return list(self.users.values())

    async def get_user(self, username):
        self._check()
        return self.users.get(username)

    async def add_user(self, username, upsk):
        self._check()
        self.users[username] = {"username": username, "uPSK": upsk}

    async def remove_user(self, username):
        self._check()
        self.users.pop(username, None)

    async def stats(self):
        self._check()
        return [dict(row) for row in self.stats_rows]


@pytest.fixture(autouse=True)
def fake_ssm(monkeypatch):
    """Every test talks to an in-memory ssm-api, never the network."""
    fake = InMemorySsm()
    monkeypatch.setattr(ssm_api, "client", fake)
    return fake


@pytest.fixture
def user_store(monkeypatch, tmp_path):
    """An empty user store on a temporary SQLite file, schema built by the Alembic migrations."""
    from alembic import command
    from alembic.config import Config
    from sqlmodel import create_engine

    url = f"sqlite:///{tmp_path / 'users.db'}"
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    monkeypatch.setattr(store, "engine", create_engine(url))
    return store
