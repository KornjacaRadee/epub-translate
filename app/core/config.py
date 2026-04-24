from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import EmailStr, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "EPUB Translate"
    environment: Literal["development", "test", "production"] = "development"
    debug: bool = False
    secret_key: str = "change-me"
    session_cookie_name: str = "epub_translate_session"
    session_max_age_seconds: int = 60 * 60 * 24 * 7
    csrf_token_ttl_seconds: int = 60 * 60 * 2
    secure_cookies: bool = False
    allowed_hosts: list[str] = ["*"]
    base_url: str = "http://localhost:8000"

    database_url: str = "postgresql+psycopg://postgres:postgres@postgres:5432/epub_translate"
    redis_url: str = "redis://redis:6379/0"
    libretranslate_url: str = "http://libretranslate:5000"
    libretranslate_api_key: str | None = None
    libretranslate_timeout_seconds: int = 60
    libretranslate_retries: int = 3

    upload_dir: Path = BASE_DIR / "uploads"
    result_dir: Path = BASE_DIR / "results"
    max_upload_size_bytes: int = 50 * 1024 * 1024
    global_free_active_job_limit: int = 2
    job_recovery_grace_seconds: int = 60
    stale_job_timeout_seconds: int = 60 * 15

    source_language: str = "en"
    target_language: str = "sr-Latn"
    glossary_path: Path = BASE_DIR / "glossary.example.yaml"
    default_admin_email: EmailStr | None = None
    default_admin_password: str | None = None

    celery_task_soft_time_limit: int = 60 * 20
    celery_task_time_limit: int = 60 * 25

    @field_validator("debug", mode="before")
    @classmethod
    def parse_debug(cls, value):
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off", "release", "prod", "production"}:
                return False
        return value


settings = Settings()
