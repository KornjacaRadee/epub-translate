from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.app_setting import AppSetting


FREE_POOL_LIMIT_KEY = "global_free_active_job_limit"


def get_setting(db: Session, key: str) -> AppSetting | None:
    return db.get(AppSetting, key)


def get_global_free_active_job_limit(db: Session) -> int:
    setting = get_setting(db, FREE_POOL_LIMIT_KEY)
    if not setting:
        return settings.global_free_active_job_limit
    try:
        return max(1, int(setting.value))
    except ValueError:
        return settings.global_free_active_job_limit


def set_global_free_active_job_limit(db: Session, value: int) -> None:
    setting = get_setting(db, FREE_POOL_LIMIT_KEY)
    if setting is None:
        setting = AppSetting(key=FREE_POOL_LIMIT_KEY, value=str(value))
    else:
        setting.value = str(value)
    db.add(setting)
    db.commit()
