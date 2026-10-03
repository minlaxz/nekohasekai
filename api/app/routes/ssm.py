import json
import logging
import os
import secrets
import string
from typing import Annotated, Any, Dict, List

import httpx
from app.auth import require_admin
from app.utils import get_stats, ssm_key
from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.requests import Request
from fastapi.responses import HTMLResponse
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


class CreatedUser(BaseModel):
    username: str
    uPSK: str
    import_url: str
    config_url: str


class DeletedUser(BaseModel):
    deleted: str


class Stats(BaseModel):
    users: List[Dict[str, Any]]


def wants_html(request: Request) -> bool:
    return "text/html" in request.headers.get("accept", "")


@router.get(
    "/server/v1/users",
    response_model=Stats,
    summary="Per-user traffic stats",
    description="HTML table for browsers; JSON with `Accept: application/json`.",
)
async def proxy_server_users(request: Request):
    stats: List[Dict[str, Any]] = await get_stats()
    if wants_html(request):
        return templates.TemplateResponse(request, "users.html", {"users": stats})
    return {"users": stats}


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


async def create_user_in_file(username: str, uPSK: str):
    users = _read_users()
    users["users"].append({"name": username, "password": uPSK, "admin": False})
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


async def seed_users_from_file() -> None:
    """Add-only: every user in users.json exists in ssm-api. Never deletes."""
    users = _read_users()["users"]
    existing = await _upstream_usernames()
    async with httpx.AsyncClient(timeout=5) as client:
        added = []
        for u in users:
            if u["name"] in existing:
                continue
            try:
                key = ssm_key(u["password"])
            except ValueError as exc:  # ssm-api keeps a user whose key fails to apply: never post it
                logging.error(f"users.json seed: skipping {u['name']}: {exc}")
                continue
            r = await client.post(
                f"{APP_SSM_UPSTREAM}/server/v1/users",
                json={"username": u["name"], "uPSK": key},
            )
            r.raise_for_status()
            added.append(u["name"])
        logging.info(f"users.json seed: {len(added)} added {added}, {len(existing)} existing")


@router.get("/form", include_in_schema=False)
async def get_form(request: Request):
    return templates.TemplateResponse(request, "form.html", {"pattern": USERNAME_PATTERN})


@router.post(
    "/create",
    response_model=CreatedUser,
    summary="Create a Managed user",
    description=(
        "Form-encoded `username` only; the PSK is generated. "
        "HTML result page for browsers; JSON with `Accept: application/json`. "
        "409 if the username already exists (delete first to rotate the PSK)."
    ),
    responses={400: {"description": "Invalid username"}, 409: {"description": "Username exists"}},
)
async def create_user(request: Request, username: Username):
    if await _user_exists(username):
        raise HTTPException(status_code=409, detail=f"User '{username}' already exists")

    uPSK = create_upsk()  # what the user holds; ssm-api gets the derived SS-2022 key (#24)
    await create_user_in_memory(username, ssm_key(uPSK))
    await create_user_in_file(username, uPSK)

    import_url = f"https://{APP_HOST}/i?j={username}&k={uPSK}"
    config_url = f"https://{APP_HOST}/c?j={username}&k={uPSK}"
    if wants_html(request):
        return templates.TemplateResponse(
            request, "form.html", {"import_url": import_url, "config_url": config_url}
        )
    return CreatedUser(username=username, uPSK=uPSK, import_url=import_url, config_url=config_url)


@router.post(
    "/delete",
    response_model=DeletedUser,
    summary="Delete a Managed user",
    description="Form-encoded `username`. 404 if the user is unknown.",
    responses={404: {"description": "Unknown username"}},
)
async def delete_user(username: Username):
    if not await _user_exists(username):
        raise HTTPException(status_code=404, detail=f"User '{username}' not found")
    await delete_user_in_memory(username)
    await delete_user_in_file(username)
    return {"deleted": username}
