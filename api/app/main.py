import logging
import os
import urllib.parse
from contextlib import asynccontextmanager
from typing import Any, Callable, Dict, Type, Union

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.requests import Request
from fastapi.responses import JSONResponse, Response, HTMLResponse

# from pydantic import BaseModel
from fastapi.templating import Jinja2Templates

from .routes.ssm import router as ssm_router
from .routes.ssm_transparent import router as ssm_transparent_router
from .utils import Reader, get_stats

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


async def check_quota_exceeded_task() -> None:
    """Pretend this function notify via Telegram when quota is exceeded"""
    stats = await get_stats()
    if len(stats) > 10:  # Arbitrary threshold for demonstration
        logging.info(f"Top 5 users: {stats[:5]}")
    else:
        logging.info("Quota check omitted.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Run once at startup
    scheduler.add_job(  # type: ignore
        check_quota_exceeded_task,
        "interval",
        seconds=60,
    )
    scheduler.start()  # type: ignore

    yield  # App runs here

    # App tearsdown: cleanup logic on shutdown and so on
    scheduler.shutdown()  # type: ignore


app = FastAPI(exception_handlers=exceptions, lifespan=lifespan)
# Both ssm and ssm-transparent routes should be protected by some authentication
app.include_router(ssm_router, prefix="/ssm")
app.include_router(ssm_transparent_router, prefix="/ssm-transparent")


origins = [
    "http://localhost",
    "http://localhost:8080",
]
APP_HOST = os.getenv("APP_HOST", "")
if APP_HOST:
    origins.append(APP_HOST)
else:
    logging.critical("APP_HOST is not set in environment variables!")
    # exit(1)


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
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/c", response_class=JSONResponse)
def read_config(
    request: Request,
    # Common options
    p: str = os.getenv("APP_DEFAULT_PLATFORM", "a"),
    v: int = int(os.getenv("APP_DEFAULT_VERSION", 12)),
    ll: str = os.getenv("APP_DEFAULT_LOG_LEVEL", "warn"),
    # DNS options
    dh: str = os.getenv("APP_DEFAULT_DNS_HOST", "dns.nextdns.io"),
    dp: str = os.getenv("APP_DEFAULT_DNS_PATH", "/"),
    dd: str = os.getenv("APP_DEFAULT_DNS_DETOUR", "Out"),
    df: str = os.getenv("APP_DEFAULT_DNS_FINAL", "dns-remote"),
    dr: str = os.getenv("APP_DEFAULT_DNS_RESOLVER", "1.1.1.1"),
    dv: int = int(os.getenv("APP_DEFAULT_DNS_VERSION", 4)),
    ddr: str = os.getenv("APP_DEFAULT_DEFAULT_DOMAIN_RESOLVER", "dns-remote"),
    # Route options
    rd: str = os.getenv("APP_DEFAULT_ROUTE_DETOUR", "Out"),
    crs: str = "",  # Custom Route Rule Sets, APP_DEFAULT_OTHER_RULE_SETS has higher priority
    # User authentication
    j: str = "",  # Required
    k: str = "",  # Required
    # Experimental options
    mx: bool = os.getenv("APP_DEFAULT_MULTIPLEX_ENABLED") == "true",
    please: bool = False,
    # Humorous parameter to appease the server
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

    # Check client platform from User-Agent header.
    user_agent: str = request.headers.get("user-agent") or ""
    if user_agent:
        if "SFA" in user_agent:
            p = "a"
        elif "SFI" in user_agent:
            p = "i"
        else:
            raise RequestValidationError([
                {
                    "loc": ["headers", "user-agent"],
                    "msg": "Unsupported client platform",
                    "type": "value_error.unsupported_platform",
                }
            ])
        v = 11 if "1.11.4" in user_agent.split(";")[1] else 12
    else:
        p = p  # Use the provided platform
        v = v  # Use the provided version

    real_ip = (
        request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or request.headers.get("x-real-ip")
        or (request.client.host if request.client else None),
    )
    logging.info(f"Received request: {j}-{real_ip}")

    # Server will assume default value if any parameter is missing
    return Reader(
        username=j,  # Required
        psk=k,  # Required
        platform=p,
        version=v,
        log_level=ll,
        dns_host=dh,
        dns_path=dp,
        dns_detour=dd,
        dns_final=df,
        dns_resolver=dr,
        dns_version=dv,
        default_domain_resolver=ddr,
        route_detour=rd,
        multiplex=mx,
        custom_rule_sets=crs,
    ).unwarp()


@app.get("/i", response_class=HTMLResponse)
def read_user(request: Request, p: str = "a", v: int = 12, j: str = "", k: str = ""):
    url = "https://" + APP_HOST + f"/c?p={p}&v={v}&j={j}&k={k}"
    encoded_url = f"sing-box://import-remote-profile?url={urllib.parse.quote(url)}#{j}"
    return templates.TemplateResponse(
        "render.html", {"request": request, "j": j, "encoded_url": encoded_url}
    )
