from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.config import settings
from app.db.session import SessionLocal
from app.services.bootstrap import bootstrap_admin, bootstrap_storage


@asynccontextmanager
async def lifespan(_: FastAPI):
    bootstrap_storage()
    db = SessionLocal()
    try:
        try:
            bootstrap_admin(db)
        except Exception:
            db.rollback()
    finally:
        db.close()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)
    app.include_router(router)
    app.mount("/static", StaticFiles(directory="app/static"), name="static")
    return app


app = create_app()
