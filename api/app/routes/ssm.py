import json
import os
import secrets
import string
from typing import Any, Dict, List, Optional

import httpx
from app.utils import get_stats
from fastapi import APIRouter, Form, HTTPException
from fastapi.requests import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()

APP_HOST: str = os.getenv("APP_HOST", "www.gstatic.com")
APP_SSM_UPSTREAM = os.getenv("APP_INTERNAL_SSM_UPSTREAM", "http://sing-box:8888")
APP_USERS_PATH = os.getenv("APP_INTERNAL_USERS_PATH", "/users.json")

templates = Jinja2Templates(directory="templates")


@router.get(
    "/server/v1/users",
    response_model=Dict[str, List[Dict[str, Any]]],
    response_class=HTMLResponse,
)
async def proxy_server_users(request: Request):
    stats: List[Dict[str, Any]] = await get_stats()
    return templates.TemplateResponse(
        "users.html", {"request": request, "users": stats}
    )


def create_upsk(custom_upsk: str | None):
    if custom_upsk:
        if len(custom_upsk) == 22 and custom_upsk.endswith("=="):
            return custom_upsk
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(20)) + "=="


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
    users["users"] = [u for u in users["users"] if u.get("name") != username]
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
    async with httpx.AsyncClient(timeout=5) as client:
        r = await client.get(f"{APP_SSM_UPSTREAM}/server/v1/users")
        r.raise_for_status()
        existing = {u["username"] for u in r.json().get("users", [])}
        for u in users:
            if u["name"] in existing:
                continue
            r = await client.post(
                f"{APP_SSM_UPSTREAM}/server/v1/users",
                json={"username": u["name"], "uPSK": u["password"]},
            )
            r.raise_for_status()


@router.get("/form")
async def get_form(request: Request):
    return templates.TemplateResponse("form.html", {"request": request})


@router.post("/create")
async def create_user(
    request: Request,
    username: str = Form(...),
    custom_upsk: Optional[str] = Form(None),
    platform: str = Form(...),
    version: str = Form(...),
):
    uPSK = create_upsk(custom_upsk)

    await create_user_in_memory(username, uPSK)
    await create_user_in_file(username, uPSK)

    import_url = f"https://{APP_HOST}/i?p={platform}&v={version}&j={username}&k={uPSK}"
    config_url = f"https://{APP_HOST}/c?p={platform}&v={version}&j={username}&k={uPSK}"
    return templates.TemplateResponse(
        "form.html",
        {"request": request, "import_url": import_url, "config_url": config_url},
    )


@router.post("/delete")
async def delete_user(username: str = Form(...)):
    await delete_user_in_memory(username)
    await delete_user_in_file(username)
    return {"deleted": username}
