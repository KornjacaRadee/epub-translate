from __future__ import annotations

from app.models.credit_transaction import CreditTransaction, CreditTransactionType
from app.models.job import Job
from app.models.user import User
from app.tests.helpers import build_sample_epub, extract_csrf_token


def test_authenticated_user_can_create_job(client, db_session, monkeypatch, tmp_path):
    epub_path = build_sample_epub(tmp_path / "upload.epub")
    queued: list[str] = []

    def fake_queue(job_id):
        queued.append(str(job_id))

    monkeypatch.setattr("app.api.routes.queue_translation_job", fake_queue)

    register_page = client.get("/register")
    csrf_token = extract_csrf_token(register_page.text)
    client.post(
        "/register",
        data={"email": "job@example.com", "password": "strongpass123", "csrf_token": csrf_token},
        follow_redirects=False,
    )

    jobs_page = client.get("/jobs")
    csrf_token = extract_csrf_token(jobs_page.text)
    response = client.post(
        "/jobs",
        data={
            "csrf_token": csrf_token,
            "translator_provider": "gemini",
            "source_language": "English",
            "target_language": "Serbian Latin",
        },
        files={"file": ("upload.epub", epub_path.read_bytes(), "application/epub+zip")},
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "You need 10 credits to translate this book. Buy credits to continue." in response.text
    assert not queued

    user = db_session.query(User).filter_by(email="job@example.com").one()
    user.credit_balance = 20
    db_session.add(user)
    db_session.commit()

    jobs_page = client.get("/jobs")
    csrf_token = extract_csrf_token(jobs_page.text)
    response = client.post(
        "/jobs",
        data={
            "csrf_token": csrf_token,
            "translator_provider": "gemini",
            "source_language": "English",
            "target_language": "Serbian Latin",
        },
        files={"file": ("upload.epub", epub_path.read_bytes(), "application/epub+zip")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"].startswith("/jobs/")
    assert queued
    db_session.refresh(user)
    assert user.credit_balance == 10
    job = db_session.query(Job).filter_by(user_id=user.id).one()
    assert job.credits_charged == 10
    transaction = (
        db_session.query(CreditTransaction)
        .filter_by(user_id=user.id, transaction_type=CreditTransactionType.SPEND)
        .one()
    )
    assert transaction.credit_amount == -10
    assert transaction.job_id == job.id

    detail = client.get(response.headers["location"])
    assert detail.status_code == 200
    assert "Upload received" in detail.text
    assert "Preparing the translation job." in detail.text
    assert "progress-bar-indeterminate" in detail.text


def test_local_mode_can_create_job_without_credits(client, db_session, monkeypatch, tmp_path):
    monkeypatch.setattr("app.core.config.settings.environment", "local")
    epub_path = build_sample_epub(tmp_path / "local-upload.epub")
    queued: list[str] = []

    def fake_queue(job_id):
        queued.append(str(job_id))

    monkeypatch.setattr("app.api.routes.queue_translation_job", fake_queue)

    register_page = client.get("/register")
    csrf_token = extract_csrf_token(register_page.text)
    client.post(
        "/register",
        data={"email": "local-job@example.com", "password": "strongpass123", "csrf_token": csrf_token},
        follow_redirects=False,
    )

    user = db_session.query(User).filter_by(email="local-job@example.com").one()
    assert user.credit_balance == 0

    jobs_page = client.get("/jobs")
    assert "Payment disabled" in jobs_page.text
    assert "Buy credits" not in jobs_page.text
    csrf_token = extract_csrf_token(jobs_page.text)
    response = client.post(
        "/jobs",
        data={
            "csrf_token": csrf_token,
            "translator_provider": "gemini",
            "source_language": "English",
            "target_language": "Serbian Latin",
        },
        files={"file": ("local-upload.epub", epub_path.read_bytes(), "application/epub+zip")},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert queued
    db_session.refresh(user)
    assert user.credit_balance == 0
    job = db_session.query(Job).filter_by(user_id=user.id).one()
    assert job.credits_charged == 0
    assert db_session.query(CreditTransaction).filter_by(user_id=user.id).count() == 0
