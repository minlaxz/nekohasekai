import os
import secrets

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials

_basic = HTTPBasic(auto_error=False)


def require_admin(creds: HTTPBasicCredentials | None = Depends(_basic)) -> None:
    """HTTP Basic gate for the admin surface. Fails closed when unconfigured.

    Env is read per request on purpose: cheap, and it keeps fail-closed testable.
    """
    user = os.getenv("APP_ADMIN_USER", "admin")
    password = os.getenv("APP_ADMIN_PASSWORD", "")
    ok = (
        bool(password)
        and creds is not None
        and secrets.compare_digest(creds.username.encode(), user.encode())
        and secrets.compare_digest(creds.password.encode(), password.encode())
    )
    if not ok:
        raise HTTPException(
            status_code=401,
            detail="Admin credential required",
            headers={"WWW-Authenticate": "Basic"},
        )
