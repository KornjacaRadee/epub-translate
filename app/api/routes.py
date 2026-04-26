from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.deps import admin_user, current_user
from app.core.csrf import read_csrf_token, set_csrf_cookie, validate_csrf
from app.core.config import settings
from app.core.security import new_csrf_token
from app.core.session import clear_session_cookie, set_session_cookie
from app.core.templates import templates
from app.db.session import get_db
from app.models.job import Job
from app.models.user import User, UserTier
from app.services.app_settings import get_global_free_active_job_limit, set_global_free_active_job_limit
from app.services.auth import authenticate_user, create_user, get_user_by_email
from app.services.credits import available_credit_packages, credits_enabled, translation_job_credit_cost
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
from app.services.paddle import PaddleError, create_checkout_url, extract_completed_payment, parse_webhook_payload, verify_paddle_signature
from app.services.credits import add_purchase_credits
from app.services.translation_options import all_translation_options, available_translation_options, validate_translation_request
from app.tasks.worker import queue_translation_job, resume_translation_job
from app.services.translators.gemini import GeminiTranslator
from app.services.translators.libretranslate import LibreTranslateClient


router = APIRouter()


def recover_jobs(db: Session, *, user: User | None = None) -> int:
    recoverable_jobs = find_recoverable_jobs(db, user=user)
    if not recoverable_jobs:
        return 0
    for job in recoverable_jobs:
        resume_translation_job(job.id, status=job.status, progress=job.progress)
    return mark_jobs_requeued(db, recoverable_jobs)


def optional_current_user(request: Request, db: Session) -> User | None:
    try:
        return current_user(request, db)
    except HTTPException:
        return None


def render(request: Request, template_name: str, context: dict, status_code: int = 200) -> HTMLResponse:
    csrf_token = read_csrf_token(request) or new_csrf_token()
    response = templates.TemplateResponse(
        request,
        template_name,
        {"request": request, "csrf_token": csrf_token, "credits_enabled": credits_enabled(), **context},
        status_code=status_code,
    )
    set_csrf_cookie(response, csrf_token)
    return response


@router.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    user = optional_current_user(request, db)
    if user:
        return RedirectResponse("/jobs", status_code=status.HTTP_303_SEE_OTHER)
    if not credits_enabled():
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    return render(request, "index.html", {"user": None})


@router.get("/pricing", response_class=HTMLResponse)
def pricing_page(request: Request, db: Session = Depends(get_db)):
    if not credits_enabled():
        user = optional_current_user(request, db)
        return RedirectResponse("/jobs" if user else "/login", status_code=status.HTTP_303_SEE_OTHER)
    return render(
        request,
        "pricing.html",
        {
            "user": optional_current_user(request, db),
            "packages": available_credit_packages(),
            "required_credits": translation_job_credit_cost(),
        },
    )


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
    return render(
        request,
        "jobs/list.html",
        {
            "user": user,
            "jobs": jobs,
            "error": None,
            "translation_options": all_translation_options(),
            "required_credits": translation_job_credit_cost(),
        },
    )


@router.post("/jobs")
def upload_job(
    request: Request,
    file: UploadFile,
    csrf_token: str = Form(...),
    translator_provider: str = Form(...),
    source_language: str = Form(...),
    target_language: str = Form(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    validate_csrf(request, csrf_token)
    try:
        translator_provider, source_language, target_language = validate_translation_request(
            translator_provider,
            source_language,
            target_language,
        )
        ensure_can_start_job(db, user, original_filename=file.filename or "book.epub")
        stored_filename, size = save_upload(file)
        job = create_job(
            db,
            user=user,
            original_filename=file.filename or "book.epub",
            stored_filename=stored_filename,
            file_size_bytes=size,
            translator_provider=translator_provider,
            source_language=source_language,
            target_language=target_language,
        )
        queue_translation_job(job.id)
        return RedirectResponse(f"/jobs/{job.id}", status_code=status.HTTP_303_SEE_OTHER)
    except ValueError as exc:
        db.rollback()
        mark_stale_active_jobs(db, user=user)
        jobs = list(db.scalars(select(Job).where(Job.user_id == user.id).order_by(Job.created_at.desc())))
        return render(
            request,
            "jobs/list.html",
            {
                "user": user,
                "jobs": jobs,
                "error": str(exc),
                "translation_options": all_translation_options(),
                "required_credits": translation_job_credit_cost(),
            },
            status_code=400,
        )


@router.get("/billing", response_class=HTMLResponse)
def billing_page(request: Request, user: User = Depends(current_user)):
    if not credits_enabled():
        return RedirectResponse("/jobs", status_code=status.HTTP_303_SEE_OTHER)
    return render(
        request,
        "billing/index.html",
        {
            "user": user,
            "packages": available_credit_packages(),
            "required_credits": translation_job_credit_cost(),
            "error": None,
        },
    )


@router.post("/billing/checkout")
def create_billing_checkout(
    request: Request,
    package_key: str = Form(...),
    csrf_token: str = Form(...),
    user: User = Depends(current_user),
):
    if not credits_enabled():
        return RedirectResponse("/jobs", status_code=status.HTTP_303_SEE_OTHER)
    validate_csrf(request, csrf_token)
    try:
        checkout_url = create_checkout_url(user_id=user.id, package_key=package_key)
    except ValueError as exc:
        return render(
            request,
            "billing/index.html",
            {
                "user": user,
                "packages": available_credit_packages(),
                "required_credits": translation_job_credit_cost(),
                "error": str(exc),
            },
            status_code=400,
        )
    except PaddleError as exc:
        return render(
            request,
            "billing/index.html",
            {
                "user": user,
                "packages": available_credit_packages(),
                "required_credits": translation_job_credit_cost(),
                "error": str(exc),
            },
            status_code=400,
        )
    return RedirectResponse(checkout_url, status_code=status.HTTP_303_SEE_OTHER)


@router.get("/billing/payment-pending", response_class=HTMLResponse)
def payment_pending_page(request: Request, user: User = Depends(current_user)):
    if not credits_enabled():
        return RedirectResponse("/jobs", status_code=status.HTTP_303_SEE_OTHER)
    return render(request, "billing/payment_pending.html", {"user": user})


@router.post("/webhooks/paddle")
async def paddle_webhook(request: Request, db: Session = Depends(get_db)):
    if not credits_enabled():
        return JSONResponse({"status": "ignored"})
    raw_body = await request.body()
    signature = request.headers.get("Paddle-Signature")
    if not verify_paddle_signature(raw_body, signature):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Paddle webhook signature.")
    try:
        payload = parse_webhook_payload(raw_body)
        payment = extract_completed_payment(payload)
        if payment is None:
            return JSONResponse({"status": "ignored"})
        add_purchase_credits(
            db,
            user_id=payment["user_id"],
            package_key=payment["package_key"],
            paddle_event_id=payment["event_id"],
            paddle_transaction_id=payment["paddle_transaction_id"],
            payment_amount=payment["payment_amount"],
            currency=payment["currency"],
            payment_status=payment["status"],
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Paddle webhook.") from exc
    return JSONResponse({"status": "ok"})


@router.get("/terms-and-conditions", response_class=HTMLResponse)
def terms_page(request: Request, db: Session = Depends(get_db)):
    return render(request, "legal/terms.html", {"user": optional_current_user(request, db)})


@router.get("/privacy-policy", response_class=HTMLResponse)
def privacy_page(request: Request, db: Session = Depends(get_db)):
    return render(request, "legal/privacy.html", {"user": optional_current_user(request, db)})


@router.get("/refund-policy", response_class=HTMLResponse)
def refund_policy_page(request: Request, db: Session = Depends(get_db)):
    return render(request, "legal/refund.html", {"user": optional_current_user(request, db)})


@router.get("/self-hosting", response_class=HTMLResponse)
def self_hosting_page(request: Request, db: Session = Depends(get_db)):
    return render(request, "self_hosting.html", {"user": optional_current_user(request, db)})


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
    if settings.enable_libretranslate:
        try:
            libretranslate_ok = LibreTranslateClient().healthcheck()
        except Exception:
            libretranslate_ok = False
    gemini_ok = False
    try:
        if any(option.id == "gemini" for option in available_translation_options()):
            gemini_ok = GeminiTranslator().healthcheck()
    except Exception:
        gemini_ok = False
    return {"status": "ok", "database": True, "libretranslate": libretranslate_ok, "gemini": gemini_ok}
