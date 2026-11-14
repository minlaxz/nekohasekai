"""Managed user lifecycle: the rules for changing User records and keeping ssm-api in line with them.
Knows nothing about HTTP; main.py maps the domain errors below to responses."""

import calendar
import logging
import secrets
import string
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app import ssm_api, store
from app.utils import ssm_key

USERNAME_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,31}$"
# Whole calendar months of access, (least, most).
CREATE_MONTHS = (0, 6)
RENEW_MONTHS = (1, 6)
TRIAL_DAYS = 3  # added on create, not on Renewal


# --- Domain errors ----------------------------------------------------------------


class UserNotFound(Exception):
    def __init__(self, username: str):
        super().__init__(f"User '{username}' not found")


class UserExists(Exception):
    def __init__(self, username: str):
        super().__init__(f"User '{username}' already exists")


class AdminEntry(Exception):
    def __init__(self, username: str):
        super().__init__(f"User '{username}' is an admin entry")


class InvalidField(Exception):
    def __init__(self, field: str, msg: str):
        super().__init__(f"{field}: {msg}")
        self.field, self.msg = field, msg


class ImportRejected(Exception):
    def __init__(self, errors: List[str]):
        super().__init__("; ".join(errors))
        self.errors = errors  # `row N: reason`, the header is row 1


# --- Clock and Expiry -------------------------------------------------------------


def now() -> datetime:
    """The one clock of the lifecycle; tests freeze it."""
    return datetime.now(timezone.utc)


def add_months(dt: datetime, months: int) -> datetime:
    """Calendar months; the day clamps to the target month (Jan 31 + 1 = Feb 28)."""
    month0 = dt.month - 1 + months
    year, month = dt.year + month0 // 12, month0 % 12 + 1
    return dt.replace(year=year, month=month, day=min(dt.day, calendar.monthrange(year, month)[1]))


def _expiry_of(entry: Dict[str, Any]) -> Optional[datetime]:
    at = entry.get("expires_at")
    if not at:
        return None
    dt = datetime.fromisoformat(at)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)  # hand-edited value without zone


def is_expired(entry: Dict[str, Any], at: datetime) -> bool:
    expiry = _expiry_of(entry)
    return expiry is not None and expiry <= at


def is_out(entry: Dict[str, Any], at: datetime) -> bool:
    """Kept out of ssm-api: Expired or Disabled."""
    return bool(entry.get("disabled")) or is_expired(entry, at)


# --- Create and delete -----------------------------------------------------------


def new_psk() -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(20)) + "=="


async def _exists(username: str) -> bool:
    """In the store, or only in ssm-api."""
    return store.get(username) is not None or username in await _ssm_usernames()


async def create(username: str, months: int) -> Dict[str, Any]:
    """Generates the PSK; Expiry is now plus `months` plus the Trial period. Returns the User record."""
    if await _exists(username):
        raise UserExists(username)
    psk = new_psk()  # what the user holds; ssm-api gets the derived SS-2022 key (#24)
    expires_at = (add_months(now(), months) + timedelta(days=TRIAL_DAYS)).isoformat()
    # Record first: a failure in between must not leave an ssm-api user with no Expiry.
    store.add(name=username, password=psk, expires_at=expires_at)
    try:
        await ssm_api.client.add_user(username, ssm_key(psk))
    except ssm_api.SsmUnavailable:
        store.delete(username)  # the admin never saw this PSK
        raise
    entry = store.get(username)
    if entry is None:  # deleted meanwhile
        raise UserNotFound(username)
    return entry


async def delete(username: str) -> None:
    """Also deletes a user who is in ssm-api but has no User record. ssm-api first: when it fails, the record is kept."""
    entry = store.get(username)
    if entry is not None and entry.get("admin"):
        raise AdminEntry(username)
    if not await _exists(username):
        raise UserNotFound(username)
    await ssm_api.client.remove_user(username)
    store.delete(username)


# --- Last fetch -------------------------------------------------------------------


def record_fetch(username: str) -> None:
    store.update(username, last_fetch=now().isoformat())


# --- Reconcile --------------------------------------------------------------------


async def _ssm_usernames() -> set[str]:
    return {u["username"] for u in await ssm_api.client.list_users()}


async def reconcile() -> None:
    """ssm-api mirrors the User records: Expired and Disabled users out, live users in.
    ssm-api users with no User record are left alone."""
    at = now()
    users = store.records()
    existing = await _ssm_usernames()
    added, removed = [], []
    for u in users:
        if is_out(u, at):
            if u["name"] in existing:
                await ssm_api.client.remove_user(u["name"])
                removed.append(u["name"])
        elif u["name"] not in existing:
            try:
                key = ssm_key(u["password"])
            except ValueError as exc:  # ssm-api keeps a user whose key fails to apply: never post it
                logging.error(f"reconcile: skipping {u['name']}: {exc}")
                continue
            await ssm_api.client.add_user(u["name"], key)
            added.append(u["name"])
    if added or removed:
        logging.info(f"reconcile: added {added}, removed {removed}")
