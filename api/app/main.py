from typing import Union, Callable, Type, Any, Dict

from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse, Response
from fastapi.requests import Request
from fastapi.exceptions import RequestValidationError

from .utils import Checker


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
def health_check(j: Union[str, None] = None, k: Union[str, None] = None) -> Response:
    if j is None or k is None:
        raise RequestValidationError([
            {
                "loc": ["query", "j" if j is None else "k"],
                "msg": "field required",
                "type": "value_error.missing",
            }
        ])
    return Response(status_code=204)


@app.get("/c", response_class=JSONResponse)
def read_config(
    p: Union[str, None] = "a",
    v: Union[int, None] = 12,
    dp: Union[str, None] = "/",
    dd: Union[str, None] = "shadowsocks",
    df: Union[str, None] = "dns-remote",
    dr: Union[str, None] = "1.1.1.1",
    rd: Union[str, None] = "direct",
    ll: Union[str, None] = "warn",
    j: Union[str, None] = None,
    k: Union[str, None] = None,
    please: bool = False,
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
        dns_path=dp,
        dns_detour=dd,
        dns_final=df,
        dns_resolver=dr,
        log_level=ll,
        route_detour=rd,
        username=j,
        psk=k,
        please=please,
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
