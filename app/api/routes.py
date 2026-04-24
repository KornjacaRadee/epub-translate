from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.deps import admin_user, current_user
from app.core.csrf import read_csrf_token, set_csrf_cookie, validate_csrf
from app.core.security import new_csrf_token
from app.core.session import clear_session_cookie, set_session_cookie
from app.core.templates import templates
from app.db.session import get_db
from app.models.job import Job
from app.models.user import User, UserTier
from app.services.app_settings import get_global_free_active_job_limit, set_global_free_active_job_limit
from app.services.auth import authenticate_user, create_user, get_user_by_email
from app.services.filenames import translated_filename_from_title
from app.services.jobs import (
    create_job,
    ensure_can_start_job,
    find_recoverable_jobs,
    get_job_by_id,
    get_job_for_user,
    mark_jobs_requeued,
    mark_stale_active_jobs,
)
from app.services.storage import result_path, save_upload
from app.tasks.worker import queue_translation_job, resume_translation_job
from app.services.translators.libretranslate import LibreTranslateClient


router = APIRouter()


def recover_jobs(db: Session, *, user: User | None = None) -> int:
    recoverable_jobs = find_recoverable_jobs(db, user=user)
    if not recoverable_jobs:
        return 0
    for job in recoverable_jobs:
        resume_translation_job(job.id, status=job.status, progress=job.progress)
    return mark_jobs_requeued(db, recoverable_jobs)


def render(request: Request, template_name: str, context: dict, status_code: int = 200) -> HTMLResponse:
    csrf_token = read_csrf_token(request) or new_csrf_token()
    response = templates.TemplateResponse(
        request,
        template_name,
        {"request": request, "csrf_token": csrf_token, **context},
        status_code=status_code,
    )
    set_csrf_cookie(response, csrf_token)
    return response


@router.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    user = None
    try:
        user = current_user(request, db)
    except HTTPException:
        pass
    if user:
        return RedirectResponse("/jobs", status_code=status.HTTP_303_SEE_OTHER)
    return render(request, "index.html", {"user": None})


@router.get("/register", response_class=HTMLResponse)
def register_form(request: Request):
    return render(request, "auth/register.html", {"error": None})


@router.post("/register", response_class=HTMLResponse)
def register(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    validate_csrf(request, csrf_token)
    if get_user_by_email(db, email):
        return render(request, "auth/register.html", {"error": "An account with that email already exists."}, status_code=400)
    if len(password) < 8:
        return render(request, "auth/register.html", {"error": "Password must be at least 8 characters."}, status_code=400)
    user = create_user(db, email, password)
    redirect = RedirectResponse("/jobs", status_code=status.HTTP_303_SEE_OTHER)
    set_session_cookie(redirect, str(user.id))
    return redirect


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return render(request, "auth/login.html", {"error": None})


@router.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    validate_csrf(request, csrf_token)
    user = authenticate_user(db, email, password)
    if not user:
        return render(request, "auth/login.html", {"error": "Invalid email or password."}, status_code=400)
    redirect = RedirectResponse("/jobs", status_code=status.HTTP_303_SEE_OTHER)
    set_session_cookie(redirect, str(user.id))
    return redirect


@router.post("/logout")
def logout(request: Request, csrf_token: str = Form(...)):
    validate_csrf(request, csrf_token)
    redirect = RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    clear_session_cookie(redirect)
    return redirect


@router.get("/logout")
def logout_get():
    return RedirectResponse("/jobs", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/jobs", response_class=HTMLResponse)
def jobs_page(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    mark_stale_active_jobs(db, user=user)
    recover_jobs(db, user=user)
    jobs = list(db.scalars(select(Job).where(Job.user_id == user.id).order_by(Job.created_at.desc())))
    return render(request, "jobs/list.html", {"user": user, "jobs": jobs, "error": None})


@router.post("/jobs")
def upload_job(
    request: Request,
    file: UploadFile,
    csrf_token: str = Form(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    validate_csrf(request, csrf_token)
    try:
        ensure_can_start_job(db, user, original_filename=file.filename or "book.epub")
        stored_filename, size = save_upload(file)
        job = create_job(db, user=user, original_filename=file.filename or "book.epub", stored_filename=stored_filename, file_size_bytes=size)
        queue_translation_job(job.id)
        return RedirectResponse(f"/jobs/{job.id}", status_code=status.HTTP_303_SEE_OTHER)
    except ValueError as exc:
        mark_stale_active_jobs(db, user=user)
        jobs = list(db.scalars(select(Job).where(Job.user_id == user.id).order_by(Job.created_at.desc())))
        return render(request, "jobs/list.html", {"user": user, "jobs": jobs, "error": str(exc)}, status_code=400)


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_status_page(job_id: uuid.UUID, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    mark_stale_active_jobs(db, user=user)
    recover_jobs(db, user=user)
    job = get_job_for_user(db, job_id, user)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return render(request, "jobs/detail.html", {"user": user, "job": job})


@router.get("/jobs/{job_id}/download")
def download_job(job_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    job = get_job_for_user(db, job_id, user)
    if not job or job.status.value != "completed" or not job.result_filename:
        raise HTTPException(status_code=404, detail="Translated EPUB not available.")
    path = result_path(job.result_filename)
    if not path.exists():
        raise HTTPException(status_code=404, detail="File missing.")
    visible_name = job.visible_result_filename or translated_filename_from_title(job.translated_title, job.original_filename)
    return FileResponse(path, media_type="application/epub+zip", filename=visible_name)


@router.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    jobs = list(db.scalars(select(Job).order_by(Job.created_at.desc()).limit(50)))
    users = list(db.scalars(select(User).order_by(User.created_at.desc()).limit(50)))
    current_limit = get_global_free_active_job_limit(db)
    return render(request, "admin/index.html", {"user": user, "jobs": jobs, "users": users, "current_limit": current_limit, "error": None})


@router.post("/admin/settings/free-pool")
def update_free_pool_limit(
    request: Request,
    free_pool_limit: int = Form(...),
    csrf_token: str = Form(...),
    user: User = Depends(admin_user),
    db: Session = Depends(get_db),
):
    validate_csrf(request, csrf_token)
    if free_pool_limit < 1:
        jobs = list(db.scalars(select(Job).order_by(Job.created_at.desc()).limit(50)))
        users = list(db.scalars(select(User).order_by(User.created_at.desc()).limit(50)))
        current_limit = get_global_free_active_job_limit(db)
        return render(
            request,
            "admin/index.html",
            {"user": user, "jobs": jobs, "users": users, "current_limit": current_limit, "error": "Free pool limit must be at least 1."},
            status_code=400,
        )
    set_global_free_active_job_limit(db, free_pool_limit)
    return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    libretranslate_ok = False
    try:
        libretranslate_ok = LibreTranslateClient().healthcheck()
    except Exception:
        libretranslate_ok = False
    return {"status": "ok", "database": True, "libretranslate": libretranslate_ok}
