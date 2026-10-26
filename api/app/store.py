"""User store (ADR 0006): the only reader and writer of User records. One transaction per write.
Records go in and out as plain dicts with every field present (None / False when not set)."""

import os
from typing import Any, Dict, List, Optional

from sqlmodel import Field, Session, SQLModel, create_engine, select

APP_DB_PATH = os.getenv("APP_INTERNAL_DB_PATH", "/data/users.db")
DB_URL = f"sqlite:///{APP_DB_PATH}"


class User(SQLModel, table=True):
    __tablename__ = "users"

    name: str = Field(primary_key=True)
    password: str = Field(unique=True)  # the PSK `k`; SS-2022 identifies a user by key
    admin: bool = False
    # ISO 8601 instant as given, zone kept; a SQLite DateTime would drop the zone.
    expires_at: Optional[str] = None
    disabled: bool = False
    ts_auth_key: Optional[str] = None  # Mesh key
    warp_key: Optional[str] = None
    warp_ipv6: Optional[str] = None


# check_same_thread: async routes use it on the event loop, sync routes (/c) from the threadpool.
engine = create_engine(DB_URL, connect_args={"check_same_thread": False})


def _session() -> Session:
    return Session(engine, expire_on_commit=False)


def get(name: str) -> Optional[Dict[str, Any]]:
    with _session() as s:
        u = s.get(User, name)
        return u.model_dump() if u else None


def all() -> List[Dict[str, Any]]:
    with _session() as s:
        return [u.model_dump() for u in s.exec(select(User).order_by(User.name))]


def add(**fields: Any) -> None:
    with _session() as s:
        s.add(User(**fields))
        s.commit()


def update(name: str, **fields: Any) -> Optional[Dict[str, Any]]:
    """Set `fields` on the User record; None when there is no such record."""
    with _session() as s:
        u = s.get(User, name)
        if u is None:
            return None
        for k, v in fields.items():
            setattr(u, k, v)
        s.add(u)
        s.commit()
        return u.model_dump()


def delete(name: str) -> None:
    with _session() as s:
        u = s.get(User, name)
        if u is not None:
            s.delete(u)
            s.commit()
