from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.user import User, UserTier
from app.services.auth import create_user
from app.services.storage import ensure_storage_dirs


def bootstrap_storage() -> None:
    ensure_storage_dirs()


def bootstrap_admin(db: Session) -> None:
    if not settings.default_admin_email or not settings.default_admin_password:
        return
    existing = db.scalar(select(User).where(User.email == settings.default_admin_email.lower()))
    if existing:
        return
    create_user(db, settings.default_admin_email, settings.default_admin_password, tier=UserTier.ADMIN)
