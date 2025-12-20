from typing import Union, Callable, Type, Any, Dict

import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse, Response
from fastapi.requests import Request
from fastapi.exceptions import RequestValidationError

from .utils import Checker
from .routes.ssm import router as ssm_router
from .routes.ssm_transparent import router as ssm_transparent_router


async def not_found(request: Request, exc: Any) -> Response:
    print(f"404 Error: {exc.detail}")
    return JSONResponse(
        status_code=404,
        content={"message": "The resource you are looking for is not found."},
    )


exceptions: Dict[Union[int, Type[Exception]], Callable[[Request, Any], Any]] = {
    404: not_found,
}

app = FastAPI(exception_handlers=exceptions)
# Both ssm and ssm-transparent routes should be protected by some authentication
app.include_router(ssm_router, prefix="/ssm")
app.include_router(ssm_transparent_router, prefix="/ssm-transparent")


origins = [
    "http://localhost",
    "http://localhost:8080",
]
config_host = os.getenv("CONFIG_HOST")
if config_host:
    origins.append(config_host)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class User(BaseModel):
    username: str
    psk: str
    is_active: Union[bool, None] = True


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


@app.head("/generate_204", response_class=JSONResponse, status_code=200)
def health_check(
    request: Request,
    j: Union[str, None] = None,
    k: Union[str, None] = None,
    expensive: Union[bool, None] = False,
) -> Response:
    if j is None or k is None:
        raise RequestValidationError([
            {
                "loc": ["query", "j" if j is None else "k"],
                "msg": "field required",
                "type": "value_error.missing",
            }
        ])
    user_id, _ = j, k
    print(f"""
        Health check for user: {user_id}
        Mode: {"expensive" if expensive else "normal"}
    """)
    return Response(status_code=204)


@app.get("/c", response_class=JSONResponse)
def read_config(
    # Common options
    p: Union[str, None] = "a",
    v: Union[int, None] = 12,
    ll: Union[str, None] = None,
    # DNS options
    # client defined dns_path otherwise server defined dns_path
    dh: Union[str, None] = os.getenv("DNS_HOST", "dns.nextdns.io"),
    dp: Union[str, None] = os.getenv("DNS_PATH", "/"),
    dd: Union[str, None] = None,
    df: Union[str, None] = None,
    dr: Union[str, None] = "1.1.1.1",
    # Route options
    rd: Union[str, None] = None,
    # User authentication
    j: Union[str, None] = None,
    k: Union[str, None] = None,
    # Misc options
    please: bool = False,  # Humorous parameter to appease the server
    mx: Union[bool, None] = True,
    # Experimentals and Wireguard options (not stable yet)
    # Experimental features without touching users
    ex: Union[bool, None] = False,
    wg: Union[int, None] = 0,  # WireGuard peer index
) -> dict[str, Any]:
    if j is None or k is None:
        raise RequestValidationError([
            {
                "loc": ["query", "j" if j is None else "k"],
                "msg": "field required",
                "type": "value_error.missing",
            }
        ])
    checker = Checker(
        platform=p,
        version=v,
        log_level=ll,
        dns_host=dh,
        dns_path=dp,
        dns_detour=dd,
        dns_final=df,
        dns_resolver=dr,
        route_detour=rd,
        username=j,
        psk=k,
        please=please,
        multiplex=mx,
        experimental=ex,
        wg=wg,
    )

    if not checker.verify_key():
        raise RequestValidationError([{"error": "Your key is disabled or invalid!"}])

    return checker.unwarp()


@app.get("/users/{name}")
def read_user(name: str, q: Union[str, None] = None) -> dict[str, str | None]:
    return {"name": name, "q": q}


@app.put("/users/{name}")
def update_user(name: str, user: User) -> dict[str, str]:
    return {"name": name, "psk": user.psk}
