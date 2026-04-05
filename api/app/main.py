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
from fastapi.responses import JSONResponse, Response

# from pydantic import BaseModel
from fastapi.templating import Jinja2Templates

from .routes.ssm import router as ssm_router
from .routes.ssm_transparent import router as ssm_transparent_router
from .utils import Reader, get_stats

scheduler = AsyncIOScheduler()

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


exceptions: Dict[Union[int, Type[Exception]], Callable[[Request, Any], Any]] = {
    404: not_found,
    Exception: internal_error,
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
    scheduler.add_job(
        check_quota_exceeded_task,
        "interval",
        seconds=60,
    )
    scheduler.start()

    yield  # App runs here

    # App tearsdown: cleanup logic on shutdown and so on
    scheduler.shutdown()


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
    # User authentication
    j: str = "",  # Required
    k: str = "",  # Required
    # Experimental options
    mx: bool = os.getenv("APP_DEFAULT_MULTIPLEX_ENABLED") == "true",
    ap: str = "",  # Admin password for experimental features
    please: bool = False,
    # Humorous parameter to appease the server
) -> dict[str, Any]:
    if not j or not k:
        raise RequestValidationError(
            [
                {
                    "loc": ["query", "j" if not j else "k"],
                    "msg": "field required",
                    "type": "value_error.missing",
                }
            ]
        )

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
        admin_password=ap,
    ).unwarp()


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=400,
        content={"message": "Bad request"},
    )


@app.get("/config")
def read_user(request: Request, p: str = "a", v: int = 12, j: str = "", k: str = ""):
    url = "https://" + APP_HOST + f"/c?p={p}&v={v}&j={j}&k={k}"
    encoded_url = f"sing-box://import-remote-profile?url={urllib.parse.quote(url)}#{j}"
    return templates.TemplateResponse(
        "render.html", {"request": request, "j": j, "encoded_url": encoded_url}
    )
