from __future__ import annotations

import secrets
from dataclasses import dataclass

from argon2 import PasswordHasher
from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.core.config import settings


password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except Exception:
        return False


def create_serializer(purpose: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key, salt=f"epub-translate:{purpose}")


def create_signed_value(value: str, purpose: str) -> str:
    return create_serializer(purpose).dumps(value)


def read_signed_value(value: str, purpose: str, max_age: int) -> str | None:
    serializer = create_serializer(purpose)
    try:
        return serializer.loads(value, max_age=max_age)
    except BadSignature:
        return None


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


@dataclass(slots=True)
class SessionData:
    user_id: str
