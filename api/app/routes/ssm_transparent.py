import os

import httpx
from app.auth import require_admin
from fastapi import APIRouter, Depends, Request, Response

START_PORT: int = int(os.getenv("START_PORT", "1080"))
END_PORT: int = int(os.getenv("END_PORT", "1090"))

APP_SSM_UPSTREAM = os.getenv("APP_SSM_UPSTREAM", "http://sing-box:8888")

router = APIRouter(dependencies=[Depends(require_admin)], include_in_schema=False)


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def full_proxy(path: str, request: Request):
    url = f"{APP_SSM_UPSTREAM}/{path}"

    async with httpx.AsyncClient(follow_redirects=True) as client:
        resp = await client.request(
            request.method,
            url,
            params=request.query_params,
            content=await request.body(),
            # Admin credential must not reach the upstream; host belongs to it, not us.
            headers={k: v for k, v in request.headers.items() if k.lower() not in ("authorization", "host")},
        )

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=resp.headers,
        media_type=resp.headers.get("content-type"),
    )
