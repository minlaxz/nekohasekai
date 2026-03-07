from typing import Any, Dict, List, Optional

import httpx
import secrets
import string
import os
import json

from fastapi import APIRouter, HTTPException, Form
from fastapi.requests import Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse


from app.utils import get_stats

router = APIRouter()

APP_HOST: str = os.getenv("APP_HOST", "www.gstatic.com")
START_PORT: int = int(os.getenv("START_PORT", "1080"))
END_PORT: int = int(os.getenv("END_PORT", "1090"))

APP_SSM_UPSTREAM = os.getenv("APP_SSM_UPSTREAM", "http://sing-box:8888")


@router.get(
    "/server/v1/users",
    response_model=Dict[str, List[Dict[str, Any]]],
    response_class=HTMLResponse,
)
async def proxy_server_users(
    request: Request,
    raw: Optional[bool] = False,
    bar: Optional[bool] = False,
):
    stats: List[Dict[str, Any]] = await get_stats()
    if raw:
        return {"stats": stats}

    templates = Jinja2Templates(directory="templates")
    if bar:
        # max_down = max(u["downlinkBytes"] for u in stats) or 1
        max_bytes = 30_000_000_000
        for u in stats:
            u["pct"] = (u["downlinkBytes"] + u["uplinkBytes"]) / max_bytes * 100
        return templates.TemplateResponse(
            "users-bar.html", {"request": request, "users": stats}
        )

    return templates.TemplateResponse(
        "users.html", {"request": request, "users": stats}
    )


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
        create_upstream = f"{APP_SSM_UPSTREAM}/server/v1/users"
        payload = {"username": username, "uPSK": uPSK}
        try:
            r = await client.post(create_upstream, json=payload)
            r.raise_for_status()

            with open("/public/users.json", "r") as f:
                users = json.load(f)
            with open("/configs/inbounds.json", "r") as f:
                inbounds = json.load(f)

            users["users"].append({"username": username, "uPSK": uPSK})
            inbounds["inbounds"][1]["users"] = users["users"]

            with open("/configs/inbounds.json", "w") as f:
                json.dump(inbounds, f, indent=2)

            with open("/public/users.json", "w") as f:
                json.dump(users, f, indent=2)

        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Upstream error: {str(e)}")
    url = f"https://{APP_HOST}/config?p={platform}&v={version}&j={username}&k={uPSK}"
    templates = Jinja2Templates(directory="templates")
    return templates.TemplateResponse("form.html", {"request": request, "result": url})
