from __future__ import annotations

from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.session import read_session_user_id
from app.db.session import get_db
from app.models.user import User, UserTier


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    raw_user_id = read_session_user_id(request)
    if not raw_user_id:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})
    try:
        user_id = UUID(raw_user_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session.") from exc
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found.")
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if user.tier != UserTier.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required.")
    return user
