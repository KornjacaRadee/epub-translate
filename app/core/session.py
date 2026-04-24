from __future__ import annotations

from fastapi import Request, Response

from app.core.config import settings
from app.core.security import create_signed_value, read_signed_value


SESSION_PURPOSE = "session"
CSRF_PURPOSE = "csrf"


def set_session_cookie(response: Response, user_id: str) -> None:
    signed = create_signed_value(user_id, SESSION_PURPOSE)
    response.set_cookie(
        settings.session_cookie_name,
        signed,
        max_age=settings.session_max_age_seconds,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(settings.session_cookie_name)


def read_session_user_id(request: Request) -> str | None:
    raw = request.cookies.get(settings.session_cookie_name)
    if not raw:
        return None
    return read_signed_value(raw, SESSION_PURPOSE, settings.session_max_age_seconds)
