from typing import Any, Dict, List, cast, Optional

import httpx
import secrets
import string
import os

from fastapi import APIRouter, HTTPException, Form
from fastapi.requests import Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse

router = APIRouter()

APP_HOST: str = os.getenv("APP_HOST", "www.gstatic.com")
START_PORT: int = int(os.getenv("START_PORT", "1080"))
END_PORT: int = int(os.getenv("END_PORT", "1090"))

APP_SSM_SERVER: str = os.getenv("APP_SSM_SERVER", "nekohasekai")
SSM_UPSTREAM = f"http://{APP_SSM_SERVER}:{END_PORT}"

@router.get(
    "/server/v1",
    response_model=Dict[str, List[Dict[str, Any]]],
    response_class=JSONResponse,
)
async def proxy_server_info():
    async with httpx.AsyncClient(timeout=5) as client:
        upstream = f"{SSM_UPSTREAM}/server/v1"
        try:
            r = await client.get(upstream)
            r.raise_for_status()
            return r.json()  # forward upstream JSON to client
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Upstream error: {str(e)}")


@router.get(
    "/server/v1/stats",
    response_model=Dict[str, List[Dict[str, Any]]],
    response_class=JSONResponse,
)
async def proxy_server_stats():
    async with httpx.AsyncClient(timeout=5) as client:
        stats_upstream = f"{SSM_UPSTREAM}/server/v1/stats"
        try:
            r = await client.get(stats_upstream)
            r.raise_for_status()
            data = r.json()
            del data["users"]
            for k, v in data.items():
                if k.endswith("Bytes"):
                    if v >= 1 << 30:
                        data[k] = f"{v / (1 << 30):.2f} GB"
                    elif v >= 1 << 20:
                        data[k] = f"{v / (1 << 20):.2f} MB"
                    elif v >= 1 << 10:
                        data[k] = f"{v / (1 << 10):.2f} KB"
                    else:
                        data[k] = f"{v} B"
                elif k.endswith("Packets"):
                    if v >= 1_000_000:
                        data[k] = f"{v / 1_000_000:.2f} M"
                    elif v >= 1_000:
                        data[k] = f"{v / 1_000:.2f} K"
                    else:
                        data[k] = f"{v}"
            return data
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Upstream error: {str(e)}")


@router.get(
    "/server/v1/users",
    response_model=Dict[str, List[Dict[str, Any]]],
    response_class=JSONResponse,
)
async def proxy_server_users():
    async with httpx.AsyncClient(timeout=5) as client:
        stats_upstream = f"{SSM_UPSTREAM}/server/v1/stats"
        users_upstream = f"{SSM_UPSTREAM}/server/v1/users"
        try:
            stats_r = await client.get(stats_upstream)
            users_r = await client.get(users_upstream)
            users_r.raise_for_status()
            stats_r.raise_for_status()
            stats_data_raw = stats_r.json()["users"]
            stats_data: List[Dict[str, Any]] = cast(
                List[Dict[str, Any]], stats_data_raw
            )
            users_data_raw = users_r.json()["users"]
            users_data: List[Dict[str, int]] = cast(
                List[Dict[str, Any]], users_data_raw
            )
            # inject uPSK from users_data into stats_data based on matching username
            users_dict = {user["username"]: user for user in users_data}
            for stat in stats_data:
                username = stat["username"]
                if username in users_dict:
                    stat["uPSK"] = users_dict[username].get("uPSK", None)
            # sort by most downlinkBytes used
            stats_data.sort(key=lambda x: int(x.get("downlinkBytes", 0)), reverse=True)
            for i in stats_data:
                for k, v in i.items():
                    if k.endswith("Bytes"):
                        if v >= 1 << 30:
                            i[k] = f"{v / (1 << 30):.2f} GB"
                        elif v >= 1 << 20:
                            i[k] = f"{v / (1 << 20):.2f} MB"
                        elif v >= 1 << 10:
                            i[k] = f"{v / (1 << 10):.2f} KB"
                        else:
                            i[k] = f"{v} B"
                    elif k.endswith("Packets"):
                        if v >= 1_000_000:
                            i[k] = f"{v / 1_000_000:.2f} M"
                        elif v >= 1_000:
                            i[k] = f"{v / 1_000:.2f} K"
                        else:
                            i[k] = f"{v}"
            return {"users": stats_data}
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Upstream error: {str(e)}")


def create_upsk(custom_upsk: str | None):
    if custom_upsk:
        if len(custom_upsk) == 22 and custom_upsk.endswith("=="):
            return custom_upsk
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(20)) + "=="


@router.get("/form")
async def get_form(request: Request):
    templates = Jinja2Templates(directory="templates")
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
    # Call upstream to create user
    async with httpx.AsyncClient(timeout=5) as client:
        create_upstream = f"{SSM_UPSTREAM}/server/v1/users"
        payload = {"username": username, "uPSK": uPSK}
        try:
            r = await client.post(create_upstream, json=payload)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Upstream error: {str(e)}")
    url = f"https://{APP_HOST}/config?p={platform}&v={version}&j={username}&k={uPSK}"
    templates = Jinja2Templates(directory="templates")
    return templates.TemplateResponse("form.html", {"request": request, "result": url})
