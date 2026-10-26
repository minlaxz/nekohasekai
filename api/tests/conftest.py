import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import store  # noqa: E402


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
