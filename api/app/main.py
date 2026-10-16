import inspect
import logging
import os
import urllib.parse
from contextlib import asynccontextmanager
from typing import Any, Callable, Dict, Type, Union

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.requests import Request
from fastapi.responses import JSONResponse, Response, HTMLResponse

# from pydantic import BaseModel
from fastapi.templating import Jinja2Templates

from .routes.ssm import router as ssm_router, reconcile_users, record_fetch
from .routes.ssm_transparent import router as ssm_transparent_router
from .utils import Checker, Reader

scheduler: AsyncIOScheduler = AsyncIOScheduler()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)


async def not_found(request: Request, exc: Any) -> Response:
    logging.info(f"404 Error: {exc}")
    return JSONResponse(
        status_code=404,
        content={"message": "The resource you are looking for is not found."},
    )


async def internal_error(request: Request, exc: Exception) -> Response:
    logging.exception(f"500 Error: {exc}")
    return JSONResponse(
        status_code=500,
        content={"message": "Nice! server error occurred."},
    )


async def validation_error(request: Request, exc: RequestValidationError) -> Response:
    logging.info(f"400 Error: {exc}")
    return JSONResponse(
        status_code=400,
        content={"message": str(exc)},
    )


exceptions: Dict[Union[int, Type[Exception]], Callable[[Request, Any], Any]] = {
    404: not_found,
    Exception: internal_error,
    RequestValidationError: validation_error,
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Run once at startup
    if not os.getenv("APP_ADMIN_PASSWORD"):
        logging.critical("APP_ADMIN_PASSWORD is not set: every /ssm request will be refused")
    try:
        await reconcile_users()
    except Exception as exc:  # ssm-api not up yet, or users.json missing
        logging.warning(f"users.json reconcile skipped: {exc}")
    # Expiry enforcement (ADR 0003): ssm-api mirrors users.json every minute.
    scheduler.add_job(reconcile_users, "interval", seconds=60)  # type: ignore
    scheduler.start()  # type: ignore

    yield  # App runs here

    # App tearsdown: cleanup logic on shutdown and so on
    scheduler.shutdown()  # type: ignore


app = FastAPI(
    title="nekohasekai API",
    description=(
        "Hands out per-user sing-box profiles and manages Managed users. "
        "Admin routes under `/ssm` need HTTP Basic (`APP_ADMIN_USER` / `APP_ADMIN_PASSWORD`). "
        "See docs/api.md in the repo for the integration flow."
    ),
    # No public schema: it would tell a prober what `/` (a fake nginx page) hides.
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    exception_handlers=exceptions,
    lifespan=lifespan,
)
app.include_router(ssm_router, prefix="/ssm")
app.include_router(ssm_transparent_router, prefix="/ssm-transparent")


origins = [
    "http://localhost",
    "http://localhost:8080",
]
APP_HOST = os.getenv("APP_HOST", "")
if APP_HOST:
    origins.append(f"https://{APP_HOST}")
else:
    logging.critical("APP_HOST is not set in environment variables!")
    # exit(1)
origins += [o.strip() for o in os.getenv("APP_CORS_ORIGINS", "").split(",") if o.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# class User(BaseModel):
#     j: str
#     k: str

templates = Jinja2Templates(directory="templates")


@app.get("/")
def read_root(request: Request):
    """_Nginx Default Page_

    Returns:
        _TemplateResponse: _nginx default page_
    """
    return templates.TemplateResponse(request, "index.html")


@app.get(
    "/c",
    response_class=JSONResponse,
    tags=["profile"],
    summary="Profile config",
    description=(
        "Full sing-box client config for one user. `j` username, `k` PSK (both required, "
        "checked against ssm-api). Other params override the `APP_DEFAULT_*` values; "
        "`r` is an optional User rule set URL; `r6` the same for WARP domains (needs `dv=6`)."
    ),
)
def read_config(
    request: Request,
    # User authentication
    j: str = "",  # Required
    k: str = "",  # Required
    # Common options
    ll: str = os.getenv("APP_DEFAULT_LOG_LEVEL", ""),
    # DNS options
    dh: str = os.getenv("APP_DEFAULT_DNS_HOST", ""),
    dn: str = os.getenv("APP_DEFAULT_DNS_SNI", ""),
    dp: str = os.getenv("APP_DEFAULT_DNS_PATH", ""),
    dd: str = os.getenv("APP_DEFAULT_DNS_DETOUR", ""),
    df: str = os.getenv("APP_DEFAULT_DNS_FINAL", ""),
    dr: str = os.getenv("APP_DEFAULT_DNS_RESOLVER", ""),
    dv: int = int(os.getenv("APP_DEFAULT_DNS_VERSION", 0)),
    # User rule set URL (optional)
    r: str = "",
    # WARP domain rule set URL (optional, used with dv=6)
    r6: str = "",
    # Rule set download HTTP client tag: `proxy` (default) or `direct` (optional)
    rd: str = "",
) -> dict[str, Any]:

    # Nothing to check if `j` and `k` aren't provided.
    if not j or not k:
        raise RequestValidationError([
            {
                "loc": ["query", "j" if not j else "k"],
                "msg": "field required",
                "type": "value_error.missing",
            }
        ])

    if not dp.startswith("/"):
        raise RequestValidationError([
            {
                "loc": ["query", "dp"],
                "msg": "must start with '/'",
                "type": "value_error.invalid",
            }
        ])

    real_ip = (
        request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or request.headers.get("x-real-ip")
        or (request.client.host if request.client else None),
    )
    logging.info(f"Received request: {j}-{real_ip}")

    config = Reader(
        username=j,  # Required
        psk=k,  # Required
        log_level=ll,
        dns_host=dh,
        dns_sni=dn,
        dns_path=dp,
        dns_detour=dd,
        dns_final=df,
        dns_resolver=dr,
        dns_version=dv,
        rules_url=r,
        rules_detour=rd,
        rules_v6_url=r6,
    ).unwarp()
    record_fetch(j)
    return config


@app.get(
    "/i",
    response_class=HTMLResponse,
    tags=["profile"],
    summary="Profile import page",
    description="Wraps the `/c` URL for `j`/`k` in a `sing-box://import-remote-profile` link. Unknown params (e.g. `p`/`v` from old links) are ignored.",
)
def read_user(request: Request, j: str = "", k: str = ""):
    url = "https://" + APP_HOST + f"/c?j={j}&k={k}"
    encoded_url = f"sing-box://import-remote-profile?url={urllib.parse.quote(url)}#{j}"
    return templates.TemplateResponse(
        request, "render.html", {"j": j, "k": k, "encoded_url": encoded_url}
    )


@app.get("/help", response_class=HTMLResponse)
def read_help(request: Request, j: str = "", k: str = ""):
    """Help page: every `/c` param with its meaning and default. Valid `j`/`k`
    only; anyone else gets the same 404 as an unknown path."""
    try:
        Checker(j, k)
    except HTTPException:
        raise HTTPException(status_code=404)
    defaults = {
        name: p.default
        for name, p in inspect.signature(read_config).parameters.items()
        if name not in ("request", "j", "k")
    }
    config_url = f"https://{APP_HOST}/c?" + urllib.parse.urlencode({"j": j, "k": k})
    return templates.TemplateResponse(
        request, "help.html", {"defaults": defaults, "config_url": config_url}
    )
