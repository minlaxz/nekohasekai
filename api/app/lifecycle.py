"""Managed user lifecycle: the rules for changing User records and keeping ssm-api in line with them.
Knows nothing about HTTP; main.py maps the domain errors below to responses."""

import base64
import calendar
import csv
import io
import ipaddress
import logging
import re
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


def _instant(value: str) -> datetime:
    """ISO 8601, zone kept, no zone = UTC; ValueError when unparsable."""
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)  # typed or hand-edited without zone


def parse_expiry(value: str) -> Optional[str]:
    """An Expiry as stored: an ISO 8601 instant, or None (never) for empty."""
    value = value.strip()
    if not value:
        return None
    try:
        return _instant(value).isoformat()
    except ValueError:
        raise InvalidField("expires_at", "must be ISO 8601, e.g. 2026-12-31T00:00 (UTC when no zone is given)") from None


def _expiry_of(entry: Dict[str, Any]) -> Optional[datetime]:
    at = entry.get("expires_at")
    return _instant(at) if at else None


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
    return _get(username)  # UserNotFound when deleted meanwhile


async def delete(username: str) -> None:
    """Also deletes a user who is in ssm-api but has no User record. ssm-api first: when it fails, the record is kept."""
    entry = store.get(username)
    if entry is not None and entry.get("admin"):
        raise AdminEntry(username)
    if not await _exists(username):
        raise UserNotFound(username)
    await ssm_api.client.remove_user(username)
    store.delete(username)


# --- Renewal, Expiry, disable and enable -----------------------------------------
# Each writes the User record, then runs Reconcile, and returns the updated record.


def _get(username: str) -> Dict[str, Any]:
    entry = store.get(username)
    if entry is None:
        raise UserNotFound(username)
    return entry


def _update(username: str, **fields: Any) -> Dict[str, Any]:
    entry = store.update(username, **fields)
    if entry is None:  # missing, or deleted since it was read
        raise UserNotFound(username)
    return entry


async def renew(username: str, months: int) -> Dict[str, Any]:
    """Counts from the current Expiry, or from now when Expired or never expiring. No Trial period; does not enable."""
    at = now()
    current = _expiry_of(_get(username))
    start = current if current is not None and current > at else at
    entry = _update(username, expires_at=add_months(start, months).isoformat())
    await reconcile()
    return entry


async def set_expiry(username: str, value: str) -> Dict[str, Any]:
    """Takes effect at once: a past instant takes the user out of ssm-api, a future one or empty puts them back."""
    entry = _update(username, expires_at=parse_expiry(value))
    await reconcile()
    return entry


async def disable(username: str) -> Dict[str, Any]:
    """Out of ssm-api until enabled; the User record, PSK and Expiry are kept."""
    if _get(username).get("admin"):
        raise AdminEntry(username)
    entry = _update(username, disabled=True)
    await reconcile()
    return entry


async def enable(username: str) -> Dict[str, Any]:
    """Back into ssm-api, unless Expired."""
    entry = _update(username, disabled=False)
    await reconcile()
    return entry


# --- WARP key and Mesh key -------------------------------------------------------
# Neither affects access: no Reconcile. Admin entries allowed.


def parse_warp_key(key: str, ipv6: str) -> tuple[Optional[str], Optional[str]]:
    """The WARP key as stored: both set, or both None to clear."""
    key, ipv6 = key.strip(), ipv6.strip()
    if not key and not ipv6:
        return None, None
    if not key or not ipv6:
        raise InvalidField("warp_key" if not key else "warp_ipv6", "set both warp_key and warp_ipv6, or neither")
    bad_key = InvalidField("warp_key", "must be a WireGuard private key: base64 of 32 bytes")
    try:
        if len(base64.b64decode(key, validate=True)) != 32:
            raise bad_key
    except ValueError:
        raise bad_key from None
    bad_ipv6 = InvalidField("warp_ipv6", "must be an IPv6 address, bare or /128")
    try:
        iface = ipaddress.IPv6Interface(ipv6)  # a bare address is /128
    except ValueError:
        raise bad_ipv6 from None
    if iface.network.prefixlen != 128 or iface.scope_id:  # a %zone would reach the sing-box endpoint
        raise bad_ipv6
    return key, str(iface)


def set_warp_key(username: str, key: str, ipv6: str) -> Dict[str, Any]:
    """Both empty clears the WARP key."""
    warp_key, warp_ipv6 = parse_warp_key(key, ipv6)
    return _update(username, warp_key=warp_key, warp_ipv6=warp_ipv6)


def set_mesh_key(username: str, key: str) -> Dict[str, Any]:
    """Trimmed at the ends; empty clears the Mesh key."""
    key = key.strip()
    if any(c.isspace() for c in key):  # loose on purpose: headscale's key format changes between versions
        raise InvalidField("ts_auth_key", "must not contain whitespace")
    return _update(username, ts_auth_key=key or None)


# --- User import and User export --------------------------------------------------
# One CSV shape for both (ADR 0006); Last fetch is runtime data, not exported.

CSV_FIELDS = ["name", "password", "admin", "expires_at", "disabled", "ts_auth_key", "warp_key", "warp_ipv6"]


def _csv_cell(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    return "" if v is None else str(v)


def export_csv() -> str:
    """Every User record, booleans as true/false, empty for none."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(CSV_FIELDS)
    for u in store.records():
        w.writerow([_csv_cell(u[f]) for f in CSV_FIELDS])
    return buf.getvalue()


def _parse_bool(value: str, column: str) -> bool:
    if value not in ("true", "false", ""):  # empty = false, for hand-made files
        raise ValueError(f"bad {column} '{value}', use true or false")
    return value == "true"


def _parse_row(row: Dict[str, str]) -> Dict[str, Any]:
    """One CSV row as a User record; ValueError says what is wrong."""
    if None in row or None in row.values():
        raise ValueError(f"wrong number of cells, expected {len(CSV_FIELDS)}")
    if not re.fullmatch(USERNAME_PATTERN, row["name"]):
        raise ValueError(f"bad username '{row['name']}'")
    try:
        ssm_key(row["password"])
    except ValueError:
        raise ValueError("bad PSK") from None  # the value is a secret: not echoed
    try:
        expires_at = parse_expiry(row["expires_at"])
    except InvalidField:
        raise ValueError(f"bad Expiry '{row['expires_at'].strip()}'") from None  # not the generic `bad <field>:` form: the 400 body is fixed
    try:
        warp_key, warp_ipv6 = parse_warp_key(row["warp_key"], row["warp_ipv6"])
    except InvalidField as exc:
        raise ValueError(f"bad {exc.field}: {exc.msg}") from None
    return {
        "name": row["name"],
        "password": row["password"],
        "admin": _parse_bool(row["admin"], "admin"),
        "expires_at": expires_at,
        "disabled": _parse_bool(row["disabled"], "disabled"),
        "ts_auth_key": row["ts_auth_key"] or None,
        "warp_key": warp_key,
        "warp_ipv6": warp_ipv6,
    }


def _parse_csv(text: str) -> tuple[List[Dict[str, Any]], List[str]]:
    """User records and `row N: reason` errors; the header is row 1."""
    reader = csv.DictReader(io.StringIO(text))
    header = reader.fieldnames or []
    errors = [f"row 1: unknown column '{c}'" for c in header if c not in CSV_FIELDS]
    errors += [f"row 1: missing column '{c}'" for c in CSV_FIELDS if c not in header]
    errors += [f"row 1: repeated column '{c}'" for c in CSV_FIELDS if header.count(c) > 1]
    if errors:
        return [], errors
    # Store only, not ssm-api: on upgrade ssm-api already holds every user being imported (ADR 0006).
    existing = store.records()
    name_taken = {u["name"]: "already exists" for u in existing}
    psk_taken = {u["password"]: "already exists" for u in existing}
    rows = []
    for n, raw in enumerate(reader, start=2):
        name, psk = raw["name"], raw["password"]
        try:
            if name in name_taken:
                raise ValueError(f"name '{name}' {name_taken[name]}")
            if psk in psk_taken:
                raise ValueError(f"PSK {psk_taken[psk]}")
            rows.append(_parse_row(raw))
        except ValueError as exc:
            errors.append(f"row {n}: {exc}")
        name_taken.setdefault(name, f"repeats row {n}")
        psk_taken.setdefault(psk, f"repeats row {n}")
    return rows, errors


async def import_csv(text: str) -> List[str]:
    """Add-only and all-or-nothing: every row is checked first, then all are added in one transaction
    and Reconcile runs. Returns the added names."""
    rows, errors = _parse_csv(text)
    if errors:
        raise ImportRejected(errors)
    store.add_many(rows)
    await reconcile()
    return [r["name"] for r in rows]


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
