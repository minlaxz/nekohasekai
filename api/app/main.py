from typing import Union, Callable, Type, Any, Dict

import os
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# from pydantic import BaseModel
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse, Response
from fastapi.requests import Request
from fastapi.exceptions import RequestValidationError
import urllib.parse

from .utils import Reader
from .routes.ssm import router as ssm_router
from .routes.ssm_transparent import router as ssm_transparent_router

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

app = FastAPI(exception_handlers=exceptions)
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


@app.get("/")
def read_root():
    """_Nginx Default Page_

    Returns:
        _TemplateResponse: _nginx default page_
    """
    templates = Jinja2Templates(directory="templates")
    return templates.TemplateResponse("index.html", {"request": {}})


@app.get("/help")
def read_help():
    """_Help_

    Returns:
        _TemplateResponse: _help_
    """
    templates = Jinja2Templates(directory="templates")
    return templates.TemplateResponse("help.html", {"request": {}})


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
    # Route options
    rd: str = os.getenv("APP_DEFAULT_ROUTE_DETOUR", "Out"),
    # User authentication
    j: str = "",  # Required
    k: str = "",  # Required
    # Experimental options
    mx: bool = os.getenv("APP_DEFAULT_MULTIPLEX_ENABLED") == "true",
    ex: bool = os.getenv("APP_DEFAULT_EXPERIMENTAL_FEATURES") == "true",
    # Humorous parameter to appease the server
    please: bool = False,
) -> dict[str, Any]:
    if not j or not k:
        raise RequestValidationError([
            {
                "loc": ["query", "j" if not j else "k"],
                "msg": "field required",
                "type": "value_error.missing",
            }
        ])

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
        route_detour=rd,
        multiplex=mx,
        experimental=ex,
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
    templates = Jinja2Templates(directory="templates")
    return templates.TemplateResponse(
        "render.html", {"request": request, "j": j, "encoded_url": encoded_url}
    )
