import asyncio
import base64
import csv
import io
import ipaddress
import os
import re
from datetime import datetime, timezone
from typing import Annotated, Any, Dict, List, Optional

from app import lifecycle, ssm_api, store
from app.auth import require_admin
from app.utils import ssm_key
from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from fastapi.requests import Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

router = APIRouter(dependencies=[Depends(require_admin)], tags=["admin"])

APP_HOST: str = os.getenv("APP_HOST", "")  # main.py logs when it is unset

templates = Jinja2Templates(directory="templates")


def _ago(iso: Optional[str]) -> str:
    if not iso:
        return "never"
    s = int((lifecycle.now() - datetime.fromisoformat(iso)).total_seconds())
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if s >= size:
            return f"{s // size}{unit} ago"
    return "just now"


templates.env.filters["ago"] = _ago

# Invalid names and months fail request validation and surface through main.py's 400 handler.
Username = Annotated[str, Form(pattern=lifecycle.USERNAME_PATTERN)]
Months = Annotated[int, Form(ge=lifecycle.CREATE_MONTHS[0], le=lifecycle.CREATE_MONTHS[1])]
RenewMonths = Annotated[int, Form(ge=lifecycle.RENEW_MONTHS[0], le=lifecycle.RENEW_MONTHS[1])]


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


# --- Expiry -------------------------------------------------------------------


def _parse_expiry(value: str) -> str:
    """ISO 8601 instant, zone kept, no zone = UTC; ValueError when unparsable."""
    dt = datetime.fromisoformat(value)
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).isoformat()


# --- Stats ------------------------------------------------------------------


def format_bytes(v: int) -> str:
    if v >= 1 << 30:
        return f"{v / (1 << 30):.2f} GB"
    elif v >= 1 << 20:
        return f"{v / (1 << 20):.2f} MB"
    elif v >= 1 << 10:
        return f"{v / (1 << 10):.2f} KB"
    return f"{v} B"


def format_packets(v: int) -> str:
    if v >= 1_000_000:
        return f"{v / 1_000_000:.2f} M"
    elif v >= 1_000:
        return f"{v / 1_000:.2f} K"
    return str(v)


async def get_stats() -> List[Dict[str, Any]]:
    """ssm-api's per-user traffic, busiest first, with each user's SSM key and human-readable counters."""
    stats_data, users_data = await asyncio.gather(ssm_api.client.stats(), ssm_api.client.list_users())
    keys = {u["username"]: u.get("uPSK") for u in users_data}
    for stat in stats_data:
        if stat["username"] in keys:
            stat["uPSK"] = keys[stat["username"]]

    stats_data.sort(key=lambda x: x.get("downlinkBytes", 0), reverse=True)  # by raw bytes

    for row in stats_data:
        extra = {}
        for k, v in row.items():
            if k.endswith("Bytes"):
                extra[k + "Human"] = format_bytes(v)
            elif k.endswith("Packets"):
                extra[k + "Human"] = format_packets(v)
        row.update(extra)
    return stats_data


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
    now = lifecycle.now()
    by_name = {u["name"]: u for u in store.records()}
    for row in stats:
        entry = by_name.get(row["username"], {})
        row["expires_at"] = entry.get("expires_at")
        row["expired"] = lifecycle.is_expired(entry, now)
        row["disabled"] = bool(entry.get("disabled"))
        row["last_fetch"] = entry.get("last_fetch")
    seen = {row["username"] for row in stats}
    stats += [
        {
            "username": u["name"],
            "uPSK": u["password"],
            "expires_at": u.get("expires_at"),
            "expired": lifecycle.is_expired(u, now),
            "disabled": bool(u.get("disabled")),
            "last_fetch": u.get("last_fetch"),
        }
        for u in by_name.values()
        if u["name"] not in seen and lifecycle.is_out(u, now)
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
    if not re.fullmatch(lifecycle.USERNAME_PATTERN, row["name"]):
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
    try:
        warp_key, warp_ipv6 = _parse_warp(row["warp_key"].strip(), row["warp_ipv6"].strip())
    except lifecycle.InvalidField as exc:  # the same checks as /ssm/warp
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
        raise lifecycle.ImportRejected(errors)
    store.add_many(rows)
    await lifecycle.reconcile()
    if wants_html(request):
        return RedirectResponse("/ssm/server/v1/users", status_code=303)
    return ImportedUsers(added=[r["name"] for r in rows])


# --- Admin routes -----------------------------------------------------------


@router.get("/form", include_in_schema=False)
async def get_form(request: Request):
    return templates.TemplateResponse(request, "form.html", {"pattern": lifecycle.USERNAME_PATTERN})


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
    entry = await lifecycle.create(username, months)
    psk, expires_at = entry["password"], entry["expires_at"]
    import_url = f"https://{APP_HOST}/i?j={username}&k={psk}"
    config_url = f"https://{APP_HOST}/c?j={username}&k={psk}"
    if wants_html(request):
        return templates.TemplateResponse(
            request,
            "form.html",
            {"import_url": import_url, "config_url": config_url, "expires_at": expires_at},
        )
    return CreatedUser(
        username=username, uPSK=psk, expires_at=expires_at, import_url=import_url, config_url=config_url
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
        raise lifecycle.UserNotFound(username)

    now = lifecycle.now()
    current = lifecycle._expiry_of(entry)  # shortcut: private, until Renewal moves into the lifecycle module (#101)
    start = current if current is not None and current > now else now
    entry = store.update(username, expires_at=lifecycle.add_months(start, months).isoformat())
    if entry is None:  # deleted meanwhile
        raise lifecycle.UserNotFound(username)
    await lifecycle.reconcile()

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
            raise lifecycle.InvalidField("expires_at", "must be ISO 8601, e.g. 2026-12-31T00:00 (UTC when no zone is given)")
    entry = store.update(username, expires_at=value or None)
    if entry is None:
        raise lifecycle.UserNotFound(username)
    await lifecycle.reconcile()

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
        raise lifecycle.InvalidField("warp_key" if not key else "warp_ipv6", "set both warp_key and warp_ipv6, or neither")
    bad_key = lifecycle.InvalidField("warp_key", "must be a WireGuard private key: base64 of 32 bytes")
    try:
        if len(base64.b64decode(key, validate=True)) != 32:
            raise bad_key
    except ValueError:
        raise bad_key from None
    bad_ipv6 = lifecycle.InvalidField("warp_ipv6", "must be an IPv6 address, bare or /128")
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
        raise lifecycle.UserNotFound(username)

    if wants_html(request):
        return RedirectResponse("/ssm/server/v1/users", status_code=303)
    return WarpSet(username=username, warp_key=entry["warp_key"], warp_ipv6=entry["warp_ipv6"])


class MeshSet(BaseModel):
    username: str
    ts_auth_key: Optional[str]  # null = no Mesh key


@router.post(
    "/mesh",
    response_model=MeshSet,
    summary="Set a Managed user's Mesh key",
    description=(
        "Form-encoded `username` and `ts_auth_key` (a headscale pre-auth key). Spaces at the ends are trimmed; "
        "empty clears the Mesh key. The user's next Profile config joins the Mesh, or leaves it. Admin entries "
        "allowed. Browser form submits are redirected to the stats page. 404 if the user has no User record."
    ),
    responses={400: {"description": "Invalid username or key"}, 404: {"description": "Unknown username"}},
)
async def set_mesh(request: Request, username: Username, ts_auth_key: Annotated[str, Form()] = ""):
    key = ts_auth_key.strip()
    if any(c.isspace() for c in key):  # loose on purpose: headscale's key format changes between versions
        raise lifecycle.InvalidField("ts_auth_key", "must not contain whitespace")
    entry = store.update(username, ts_auth_key=key or None)
    if entry is None:
        raise lifecycle.UserNotFound(username)

    if wants_html(request):
        return RedirectResponse("/ssm/server/v1/users", status_code=303)
    return MeshSet(username=username, ts_auth_key=entry["ts_auth_key"])


def _refuse_admin(entry: Optional[Dict[str, Any]], username: str) -> None:
    if entry is not None and entry.get("admin"):
        raise lifecycle.AdminEntry(username)


async def _set_disabled(request: Request, username: str, disabled: bool):
    entry = store.get(username)
    if entry is None:
        raise lifecycle.UserNotFound(username)
    if disabled:
        _refuse_admin(entry, username)
    if store.update(username, disabled=disabled) is None:  # deleted meanwhile
        raise lifecycle.UserNotFound(username)
    await lifecycle.reconcile()

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
    await lifecycle.delete(username)
    if wants_html(request):
        return RedirectResponse("/ssm/server/v1/users", status_code=303)
    return {"deleted": username}
