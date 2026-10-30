import base64
import calendar
import csv
import io
import ipaddress
import logging
import os
import re
import secrets
import string
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Dict, List, Optional

import httpx
from app import store
from app.auth import require_admin
from app.utils import get_stats, ssm_key
from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.requests import Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

router = APIRouter(dependencies=[Depends(require_admin)], tags=["admin"])

APP_HOST: str = os.getenv("APP_HOST", "www.gstatic.com")
APP_SSM_UPSTREAM = os.getenv("APP_INTERNAL_SSM_UPSTREAM", "http://sing-box:8888")

templates = Jinja2Templates(directory="templates")


def record_fetch(username: str) -> None:
    store.update(username, last_fetch=_now().isoformat())


def _ago(iso: Optional[str]) -> str:
    if not iso:
        return "never"
    s = int((_now() - datetime.fromisoformat(iso)).total_seconds())
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if s >= size:
            return f"{s // size}{unit} ago"
    return "just now"


templates.env.filters["ago"] = _ago

USERNAME_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,31}$"
# Invalid names fail request validation and surface through main.py's 400 handler.
Username = Annotated[str, Form(pattern=USERNAME_PATTERN)]
# Whole calendar months of access. Create adds the Trial period on top; renew does not.
Months = Annotated[int, Form(ge=0, le=6)]
RenewMonths = Annotated[int, Form(ge=1, le=6)]
TRIAL_DAYS = 3


class CreatedUser(BaseModel):
    username: str
    uPSK: str
    expires_at: str
    import_url: str
    config_url: str


class RenewedUser(BaseModel):
    username: str
    expires_at: str


class ExpirySet(BaseModel):
    username: str
    expires_at: Optional[str]  # null = never expires


class DeletedUser(BaseModel):
    deleted: str


class DisabledSet(BaseModel):
    username: str
    disabled: bool


class Stats(BaseModel):
    users: List[Dict[str, Any]]


def wants_html(request: Request) -> bool:
    return "text/html" in request.headers.get("accept", "")


def _bad_field(field: str, msg: str) -> RequestValidationError:
    """A 400 naming the bad form field, through main.py's handler."""
    return RequestValidationError([{"loc": ["body", field], "msg": msg, "type": "value_error.invalid"}])


# --- Expiry -------------------------------------------------------------------


def _now() -> datetime:
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


def _parse_expiry(value: str) -> str:
    """ISO 8601 instant, zone kept, no zone = UTC; ValueError when unparsable."""
    dt = datetime.fromisoformat(value)
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).isoformat()


def is_expired(entry: Dict[str, Any], now: datetime) -> bool:
    at = _expiry_of(entry)
    return at is not None and at <= now


def is_out(entry: Dict[str, Any], now: datetime) -> bool:
    """Kept out of ssm-api: Expired or Disabled."""
    return bool(entry.get("disabled")) or is_expired(entry, now)


# --- Stats ------------------------------------------------------------------


@router.get(
    "/server/v1/users",
    response_model=Stats,
    summary="Per-user traffic stats",
    description=(
        "HTML table for browsers; JSON with `Accept: application/json`. Every row carries "
        "`expires_at` (null = never), `expired`, `disabled` and `last_fetch` (null = never fetched); Expired and Disabled users are listed from "
        "their User records with no traffic."
    ),
)
async def proxy_server_users(request: Request):
    stats: List[Dict[str, Any]] = await get_stats()
    now = _now()
    by_name = {u["name"]: u for u in store.records()}
    for row in stats:
        entry = by_name.get(row["username"], {})
        row["expires_at"] = entry.get("expires_at")
        row["expired"] = is_expired(entry, now)
        row["disabled"] = bool(entry.get("disabled"))
        row["last_fetch"] = entry.get("last_fetch")
    seen = {row["username"] for row in stats}
    stats += [
        {
            "username": u["name"],
            "uPSK": u["password"],
            "expires_at": u.get("expires_at"),
            "expired": is_expired(u, now),
            "disabled": bool(u.get("disabled")),
            "last_fetch": u.get("last_fetch"),
        }
        for u in by_name.values()
        if u["name"] not in seen and is_out(u, now)
    ]
    if wants_html(request):
        return templates.TemplateResponse(request, "users.html", {"users": stats, "entries": by_name})
    return {"users": stats}


# --- ssm-api and User records -------------------------------------------------


# --- User export ------------------------------------------------------------

# The CSV shape User import accepts too (ADR 0006); Last fetch is runtime data, not exported.
CSV_FIELDS = ["name", "password", "admin", "expires_at", "disabled", "ts_auth_key", "warp_key", "warp_ipv6"]


def _csv_cell(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    return "" if v is None else str(v)


@router.get(
    "/export",
    summary="User export",
    description="Every User record as CSV (Last fetch excluded). Holds every PSK, Mesh key and WARP key in plain text.",
)
async def export_users():
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(CSV_FIELDS)
    for u in store.records():
        w.writerow([_csv_cell(u[f]) for f in CSV_FIELDS])
    return Response(
        buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="users.csv"', "Cache-Control": "no-store"},
    )


# --- User import ------------------------------------------------------------


class ImportedUsers(BaseModel):
    added: List[str]


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
    expires_at = row["expires_at"].strip() or None
    if expires_at:
        try:
            expires_at = _parse_expiry(expires_at)
        except ValueError:
            raise ValueError(f"bad Expiry '{expires_at}'") from None
    return {
        "name": row["name"],
        "password": row["password"],
        "admin": _parse_bool(row["admin"], "admin"),
        "expires_at": expires_at,
        "disabled": _parse_bool(row["disabled"], "disabled"),
        "ts_auth_key": row["ts_auth_key"] or None,
        "warp_key": row["warp_key"] or None,
        "warp_ipv6": row["warp_ipv6"] or None,
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


@router.post(
    "/import",
    response_model=ImportedUsers,
    summary="User import",
    description=(
        "Multipart `file`: a CSV in the User export shape. Add-only and all-or-nothing: every row is checked "
        "first, and any bad row, or any name or PSK already in the store, rejects the whole file with "
        "`400 {\"detail\": [\"row N: reason\", ...]}` (the header is row 1). On success every row is added in one "
        "transaction and live users reach ssm-api before the response returns. Browser form submits are "
        "redirected to the stats page."
    ),
    responses={400: {"description": "Bad file; nothing added"}},
)
async def import_users(request: Request, file: UploadFile):
    try:
        text = (await file.read()).decode("utf-8-sig")  # -sig: spreadsheet apps prepend a BOM
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail=["row 1: file is not UTF-8 text"])
    rows, errors = _parse_csv(text)
    if errors:
        raise HTTPException(status_code=400, detail=errors)
    store.add_many(rows)
    await reconcile_users()
    if wants_html(request):
        return RedirectResponse("/ssm/server/v1/users", status_code=303)
    return ImportedUsers(added=[r["name"] for r in rows])


def create_upsk() -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(20)) + "=="


async def _upstream_usernames() -> set[str]:
    async with httpx.AsyncClient(timeout=5) as client:
        try:
            r = await client.get(f"{APP_SSM_UPSTREAM}/server/v1/users")
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Upstream error: {str(e)}")
    return {u["username"] for u in r.json().get("users", [])}


async def _user_exists(username: str) -> bool:
    return store.get(username) is not None or username in await _upstream_usernames()


async def create_user_in_memory(username: str, uPSK: str):
    async with httpx.AsyncClient(timeout=5) as client:
        create_upstream = f"{APP_SSM_UPSTREAM}/server/v1/users"
        payload = {"username": username, "uPSK": uPSK}
        try:
            r = await client.post(create_upstream, json=payload)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Upstream error: {str(e)}")


async def delete_user_in_memory(username: str):
    async with httpx.AsyncClient(timeout=5) as client:
        try:
            r = await client.delete(f"{APP_SSM_UPSTREAM}/server/v1/users/{username}")
            if r.status_code != 404:
                r.raise_for_status()
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Upstream error: {str(e)}")


async def reconcile_users() -> None:
    """ssm-api mirrors the User records: Expired and Disabled users out, live users in.
    ssm-api users with no User record are left alone."""
    now = _now()
    users = store.records()
    existing = await _upstream_usernames()
    added, removed = [], []
    for u in users:
        if is_out(u, now):
            if u["name"] in existing:
                await delete_user_in_memory(u["name"])
                removed.append(u["name"])
        elif u["name"] not in existing:
            try:
                key = ssm_key(u["password"])
            except ValueError as exc:  # ssm-api keeps a user whose key fails to apply: never post it
                logging.error(f"reconcile: skipping {u['name']}: {exc}")
                continue
            await create_user_in_memory(u["name"], key)
            added.append(u["name"])
    if added or removed:
        logging.info(f"reconcile: added {added}, removed {removed}")


# --- Admin routes -----------------------------------------------------------


@router.get("/form", include_in_schema=False)
async def get_form(request: Request):
    return templates.TemplateResponse(request, "form.html", {"pattern": USERNAME_PATTERN})


@router.post(
    "/create",
    response_model=CreatedUser,
    summary="Create a Managed user",
    description=(
        "Form-encoded `username`, optional `months` (0 to 6, default 0); the PSK is generated. "
        "Expiry is now plus `months` calendar months plus a 3-day Trial period. "
        "HTML result page for browsers; JSON with `Accept: application/json`. "
        "409 if the username already exists (delete first to rotate the PSK)."
    ),
    responses={400: {"description": "Invalid username or months"}, 409: {"description": "Username exists"}},
)
async def create_user(request: Request, username: Username, months: Months = 0):
    if await _user_exists(username):
        raise HTTPException(status_code=409, detail=f"User '{username}' already exists")

    uPSK = create_upsk()  # what the user holds; ssm-api gets the derived SS-2022 key (#24)
    expires_at = (add_months(_now(), months) + timedelta(days=TRIAL_DAYS)).isoformat()
    await create_user_in_memory(username, ssm_key(uPSK))
    store.add(name=username, password=uPSK, expires_at=expires_at)

    import_url = f"https://{APP_HOST}/i?j={username}&k={uPSK}"
    config_url = f"https://{APP_HOST}/c?j={username}&k={uPSK}"
    if wants_html(request):
        return templates.TemplateResponse(
            request,
            "form.html",
            {"import_url": import_url, "config_url": config_url, "expires_at": expires_at},
        )
    return CreatedUser(
        username=username, uPSK=uPSK, expires_at=expires_at, import_url=import_url, config_url=config_url
    )


@router.post(
    "/renew",
    response_model=RenewedUser,
    summary="Renew a Managed user",
    description=(
        "Form-encoded `username` and `months` (1 to 6). Pushes Expiry forward by that many calendar months, "
        "counted from the current Expiry, or from now if the user is expired or has no Expiry. No Trial period. "
        "An Expired user is put back into ssm-api with the same PSK. 404 if the user has no User record."
    ),
    responses={400: {"description": "Invalid username or months"}, 404: {"description": "Unknown username"}},
)
async def renew_user(request: Request, username: Username, months: RenewMonths):
    entry = store.get(username)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"User '{username}' not found")

    now = _now()
    current = _expiry_of(entry)
    start = current if current is not None and current > now else now
    entry = store.update(username, expires_at=add_months(start, months).isoformat())
    if entry is None:  # deleted meanwhile
        raise HTTPException(status_code=404, detail=f"User '{username}' not found")
    await reconcile_users()

    if wants_html(request):
        return templates.TemplateResponse(
            request, "form.html", {"renewed": {"username": username, "expires_at": entry["expires_at"]}}
        )
    return RenewedUser(username=username, expires_at=entry["expires_at"])


@router.post(
    "/expiry",
    response_model=ExpirySet,
    summary="Set a Managed user's Expiry",
    description=(
        "Form-encoded `username` and `expires_at`: an ISO 8601 instant (no zone = UTC), or empty to never expire. "
        "Takes effect at once: a past instant removes the user from ssm-api, a future one or empty puts them back "
        "with the same PSK. Browser form submits are redirected to the stats page. 404 if the user has no User record."
    ),
    responses={400: {"description": "Invalid username or expires_at"}, 404: {"description": "Unknown username"}},
)
async def set_expiry(request: Request, username: Username, expires_at: Annotated[str, Form()] = ""):
    value = expires_at.strip()
    if value:
        try:
            value = _parse_expiry(value)
        except ValueError:
            raise _bad_field("expires_at", "must be ISO 8601, e.g. 2026-12-31T00:00 (UTC when no zone is given)")
    entry = store.update(username, expires_at=value or None)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"User '{username}' not found")
    await reconcile_users()

    if wants_html(request):
        return RedirectResponse("/ssm/server/v1/users", status_code=303)
    return ExpirySet(username=username, expires_at=entry["expires_at"])


class WarpSet(BaseModel):
    username: str
    warp_key: Optional[str]  # null = no WARP key
    warp_ipv6: Optional[str]


def _parse_warp(key: str, ipv6: str) -> tuple[Optional[str], Optional[str]]:
    """The WARP key as stored: both set, or both None to clear."""
    if not key and not ipv6:
        return None, None
    if not key or not ipv6:
        raise _bad_field("warp_key" if not key else "warp_ipv6", "set both warp_key and warp_ipv6, or neither")
    bad_key = _bad_field("warp_key", "must be a WireGuard private key: base64 of 32 bytes")
    try:
        if len(base64.b64decode(key, validate=True)) != 32:
            raise bad_key
    except ValueError:
        raise bad_key from None
    bad_ipv6 = _bad_field("warp_ipv6", "must be an IPv6 address, bare or /128")
    try:
        iface = ipaddress.IPv6Interface(ipv6)  # a bare address is /128
    except ValueError:
        raise bad_ipv6 from None
    if iface.network.prefixlen != 128 or iface.scope_id:  # a %zone would reach the sing-box endpoint
        raise bad_ipv6
    return key, str(iface)


@router.post(
    "/warp",
    response_model=WarpSet,
    summary="Set a Managed user's WARP key",
    description=(
        "Form-encoded `username`, `warp_key` (WireGuard private key, base64 of 32 bytes) and `warp_ipv6` "
        "(the WARP account's IPv6 address, bare or `/128`; stored with `/128`). Both or neither: both empty "
        "clears the WARP key. The user's next Profile config uses it. Admin entries allowed. "
        "Browser form submits are redirected to the stats page. 404 if the user has no User record."
    ),
    responses={400: {"description": "Invalid username, key or address"}, 404: {"description": "Unknown username"}},
)
async def set_warp(
    request: Request,
    username: Username,
    warp_key: Annotated[str, Form()] = "",
    warp_ipv6: Annotated[str, Form()] = "",
):
    key, ipv6 = _parse_warp(warp_key.strip(), warp_ipv6.strip())
    entry = store.update(username, warp_key=key, warp_ipv6=ipv6)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"User '{username}' not found")

    if wants_html(request):
        return RedirectResponse("/ssm/server/v1/users", status_code=303)
    return WarpSet(username=username, warp_key=entry["warp_key"], warp_ipv6=entry["warp_ipv6"])


def _refuse_admin(entry: Optional[Dict[str, Any]], username: str) -> None:
    if entry is not None and entry.get("admin"):
        raise HTTPException(status_code=403, detail=f"User '{username}' is an admin entry")


async def _set_disabled(request: Request, username: str, disabled: bool):
    entry = store.get(username)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"User '{username}' not found")
    if disabled:
        _refuse_admin(entry, username)
    if store.update(username, disabled=disabled) is None:  # deleted meanwhile
        raise HTTPException(status_code=404, detail=f"User '{username}' not found")
    await reconcile_users()

    if wants_html(request):
        return RedirectResponse("/ssm/server/v1/users", status_code=303)
    return DisabledSet(username=username, disabled=disabled)


@router.post(
    "/disable",
    response_model=DisabledSet,
    summary="Disable a Managed user",
    description=(
        "Form-encoded `username`. Removes the user from ssm-api and keeps them out until enabled; "
        "the User record, PSK and Expiry are kept. Renewal does not enable. Repeat calls are no-ops. "
        "Browser form submits are redirected to the stats page. 404 if the user has no User record, "
        "403 for an admin entry."
    ),
    responses={403: {"description": "Admin entry"}, 404: {"description": "Unknown username"}},
)
async def disable_user(request: Request, username: Username):
    return await _set_disabled(request, username, True)


@router.post(
    "/enable",
    response_model=DisabledSet,
    summary="Enable a Disabled user",
    description=(
        "Form-encoded `username`. Puts the user back into ssm-api with the same PSK, unless they are Expired. "
        "Repeat calls are no-ops. Browser form submits are redirected to the stats page. "
        "404 if the user has no User record."
    ),
    responses={404: {"description": "Unknown username"}},
)
async def enable_user(request: Request, username: Username):
    return await _set_disabled(request, username, False)


@router.post(
    "/delete",
    response_model=DeletedUser,
    summary="Delete a Managed user",
    description=(
        "Form-encoded `username`. Removes the user from ssm-api and deletes the User record; the PSK is gone. "
        "Browser form submits are redirected to the stats page. 404 if the user is unknown, 403 for an admin entry."
    ),
    responses={403: {"description": "Admin entry"}, 404: {"description": "Unknown username"}},
)
async def delete_user(request: Request, username: Username):
    _refuse_admin(store.get(username), username)
    if not await _user_exists(username):
        raise HTTPException(status_code=404, detail=f"User '{username}' not found")
    await delete_user_in_memory(username)
    store.delete(username)
    if wants_html(request):
        return RedirectResponse("/ssm/server/v1/users", status_code=303)
    return {"deleted": username}
