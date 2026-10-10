import calendar
import json
import logging
import os
import secrets
import string
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Dict, List, Optional

import httpx
from app.auth import require_admin
from app.utils import get_stats, ssm_key
from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.requests import Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

router = APIRouter(dependencies=[Depends(require_admin)], tags=["admin"])

APP_HOST: str = os.getenv("APP_HOST", "www.gstatic.com")
APP_SSM_UPSTREAM = os.getenv("APP_INTERNAL_SSM_UPSTREAM", "http://sing-box:8888")
APP_USERS_PATH = os.getenv("APP_INTERNAL_USERS_PATH", "/users.json")

templates = Jinja2Templates(directory="templates")

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
        "`expires_at` (null = never), `expired` and `disabled`; Expired and Disabled users are listed from "
        "users.json with no traffic."
    ),
)
async def proxy_server_users(request: Request):
    stats: List[Dict[str, Any]] = await get_stats()
    now = _now()
    by_name = {u["name"]: u for u in _read_users()["users"]}
    for row in stats:
        entry = by_name.get(row["username"], {})
        row["expires_at"] = entry.get("expires_at")
        row["expired"] = is_expired(entry, now)
        row["disabled"] = bool(entry.get("disabled"))
    seen = {row["username"] for row in stats}
    stats += [
        {
            "username": u["name"],
            "uPSK": u["password"],
            "expires_at": u.get("expires_at"),
            "expired": is_expired(u, now),
            "disabled": bool(u.get("disabled")),
        }
        for u in by_name.values()
        if u["name"] not in seen and is_out(u, now)
    ]
    if wants_html(request):
        return templates.TemplateResponse(request, "users.html", {"users": stats, "entries": by_name})
    return {"users": stats}


# --- ssm-api and Users file -------------------------------------------------


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
    in_file = any(u.get("name") == username for u in _read_users()["users"])
    return in_file or username in await _upstream_usernames()


async def create_user_in_memory(username: str, uPSK: str):
    async with httpx.AsyncClient(timeout=5) as client:
        create_upstream = f"{APP_SSM_UPSTREAM}/server/v1/users"
        payload = {"username": username, "uPSK": uPSK}
        try:
            r = await client.post(create_upstream, json=payload)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Upstream error: {str(e)}")


def _read_users() -> Dict[str, Any]:
    with open(APP_USERS_PATH, "r") as f:
        return json.load(f)


def _write_users(users: Dict[str, Any]) -> None:
    with open(APP_USERS_PATH, "w") as f:
        json.dump(users, f, indent=2)


async def create_user_in_file(username: str, uPSK: str, expires_at: str):
    users = _read_users()
    users["users"].append({"name": username, "password": uPSK, "admin": False, "expires_at": expires_at})
    _write_users(users)


async def delete_user_in_memory(username: str):
    async with httpx.AsyncClient(timeout=5) as client:
        try:
            r = await client.delete(f"{APP_SSM_UPSTREAM}/server/v1/users/{username}")
            if r.status_code != 404:
                r.raise_for_status()
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Upstream error: {str(e)}")


async def delete_user_in_file(username: str):
    users = _read_users()
    users["users"] = [u for u in users["users"] if u.get("name") != username]
    _write_users(users)


def _warn_duplicate_psks(users: List[Dict[str, Any]]) -> None:
    """SS-2022 identifies a user by key, not by name: two entries with one PSK are one user to
    sing-box (last name wins, stats merge, Expiry on one does nothing). Rotate one of them."""
    by_psk: Dict[str, List[str]] = {}
    for u in users:
        by_psk.setdefault(u["password"], []).append(u["name"])
    for names in by_psk.values():
        if len(names) > 1:
            logging.warning(f"users.json: duplicate PSK shared by {names}; sing-box treats them as one user")


async def reconcile_users() -> None:
    """ssm-api mirrors users.json: Expired and Disabled users out, live users in. Users unknown to the file are left alone."""
    now = _now()
    users = _read_users()["users"]
    _warn_duplicate_psks(users)
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
                logging.error(f"users.json reconcile: skipping {u['name']}: {exc}")
                continue
            await create_user_in_memory(u["name"], key)
            added.append(u["name"])
    if added or removed:
        logging.info(f"users.json reconcile: added {added}, removed {removed}")


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
    await create_user_in_file(username, uPSK, expires_at)

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
        "An Expired user is put back into ssm-api with the same PSK. 404 if the user is not in users.json."
    ),
    responses={400: {"description": "Invalid username or months"}, 404: {"description": "Unknown username"}},
)
async def renew_user(request: Request, username: Username, months: RenewMonths):
    users = _read_users()
    entry = next((u for u in users["users"] if u.get("name") == username), None)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"User '{username}' not found")

    now = _now()
    current = _expiry_of(entry)
    start = current if current is not None and current > now else now
    entry["expires_at"] = add_months(start, months).isoformat()
    _write_users(users)
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
        "with the same PSK. Browser form submits are redirected to the stats page. 404 if the user is not in users.json."
    ),
    responses={400: {"description": "Invalid username or expires_at"}, 404: {"description": "Unknown username"}},
)
async def set_expiry(request: Request, username: Username, expires_at: Annotated[str, Form()] = ""):
    users = _read_users()
    entry = next((u for u in users["users"] if u.get("name") == username), None)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"User '{username}' not found")

    value = expires_at.strip()
    if value:
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            raise RequestValidationError([
                {
                    "loc": ["body", "expires_at"],
                    "msg": "must be ISO 8601, e.g. 2026-12-31T00:00 (UTC when no zone is given)",
                    "type": "value_error.invalid",
                }
            ])
        entry["expires_at"] = (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).isoformat()
    else:
        entry.pop("expires_at", None)
    _write_users(users)
    await reconcile_users()

    if wants_html(request):
        return RedirectResponse("/ssm/server/v1/users", status_code=303)
    return ExpirySet(username=username, expires_at=entry.get("expires_at"))


def _refuse_admin(entry: Optional[Dict[str, Any]], username: str) -> None:
    if entry is not None and entry.get("admin"):
        raise HTTPException(status_code=403, detail=f"User '{username}' is an admin entry")


async def _set_disabled(request: Request, username: str, disabled: bool):
    users = _read_users()
    entry = next((u for u in users["users"] if u.get("name") == username), None)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"User '{username}' not found")
    if disabled:
        _refuse_admin(entry, username)
        entry["disabled"] = True
    else:
        entry.pop("disabled", None)
    _write_users(users)
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
        "the users.json entry, PSK and Expiry are kept. Renewal does not enable. Repeat calls are no-ops. "
        "Browser form submits are redirected to the stats page. 404 if the user is not in users.json, "
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
        "404 if the user is not in users.json."
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
        "Form-encoded `username`. Removes the user from ssm-api and users.json; the PSK is gone. "
        "Browser form submits are redirected to the stats page. 404 if the user is unknown, 403 for an admin entry."
    ),
    responses={403: {"description": "Admin entry"}, 404: {"description": "Unknown username"}},
)
async def delete_user(request: Request, username: Username):
    _refuse_admin(next((u for u in _read_users()["users"] if u.get("name") == username), None), username)
    if not await _user_exists(username):
        raise HTTPException(status_code=404, detail=f"User '{username}' not found")
    await delete_user_in_memory(username)
    await delete_user_in_file(username)
    if wants_html(request):
        return RedirectResponse("/ssm/server/v1/users", status_code=303)
    return {"deleted": username}
