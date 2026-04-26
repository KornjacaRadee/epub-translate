from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.models.user import User, UserTier
from app.services.credits import credits_enabled, grant_signup_credit


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email.lower().strip()))


def create_user(db: Session, email: str, password: str, tier: UserTier = UserTier.FREE) -> User:
    user = User(email=email.lower().strip(), password_hash=hash_password(password), tier=tier)
    db.add(user)
    db.flush()
    if credits_enabled():
        grant_signup_credit(db, user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    user = get_user_by_email(db, email)
    if not user:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user
