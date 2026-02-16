import httpx
import os
from fastapi import Request, Response, APIRouter

START_PORT: int = int(os.getenv("START_PORT", "1080"))
END_PORT: int = int(os.getenv("END_PORT", "1090"))

APP_SSM_SERVER: str = os.getenv("APP_SSM_SERVER", "nekohasekai")
SSM_UPSTREAM = f"http://{APP_SSM_SERVER}:{END_PORT}"

router = APIRouter()


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def full_proxy(path: str, request: Request):
    url = f"{SSM_UPSTREAM}/{path}"

    async with httpx.AsyncClient(follow_redirects=True) as client:
        resp = await client.request(
            request.method,
            url,
            params=request.query_params,
            content=await request.body(),
            headers=request.headers,
        )

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=resp.headers,
        media_type=resp.headers.get("content-type"),
    )
