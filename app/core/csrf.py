from __future__ import annotations

from fastapi import HTTPException, Request, Response, status

from app.core.config import settings
from app.core.security import create_signed_value, new_csrf_token, read_signed_value


CSRF_COOKIE_NAME = "csrf_token"


def set_csrf_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        CSRF_COOKIE_NAME,
        create_signed_value(token, "csrf"),
        max_age=settings.csrf_token_ttl_seconds,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
    )


def issue_csrf(response: Response) -> str:
    token = new_csrf_token()
    set_csrf_cookie(response, token)
    return token


def read_csrf_token(request: Request) -> str | None:
    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    if not cookie_token:
        return None
    return read_signed_value(cookie_token, "csrf", settings.csrf_token_ttl_seconds)


def validate_csrf(request: Request, submitted_token: str | None) -> None:
    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    if not cookie_token or not submitted_token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing CSRF token.")
    raw_cookie_token = read_signed_value(cookie_token, "csrf", settings.csrf_token_ttl_seconds)
    if not raw_cookie_token or submitted_token != raw_cookie_token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token.")
