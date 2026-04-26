from __future__ import annotations

import hmac
import json
from datetime import datetime, timedelta, timezone
from hashlib import sha256

from app.core.config import settings
from app.models.credit_transaction import CreditTransaction, CreditTransactionType
from app.models.job import Job, JobStatus
from app.models.user import User, UserTier
from app.services.credits import find_refundable_failed_jobs, refund_failed_job, spend_credits_for_job
from app.services.jobs import update_job_status
from app.tests.helpers import extract_csrf_token


def sign_paddle_payload(raw_body: bytes, secret: str, timestamp: str = "12345") -> str:
    signature = hmac.new(secret.encode("utf-8"), timestamp.encode("utf-8") + b":" + raw_body, sha256).hexdigest()
    return f"ts={timestamp};h1={signature}"


def register_user(client, email: str = "billing@example.com") -> None:
    register_page = client.get("/register")
    csrf_token = extract_csrf_token(register_page.text)
    client.post(
        "/register",
        data={"email": email, "password": "strongpass123", "csrf_token": csrf_token},
        follow_redirects=False,
    )


def test_billing_pages_and_legal_pages_exist(client):
    register_user(client)

    billing = client.get("/billing")
    assert billing.status_code == 200
    assert "Buy credits" in billing.text
    assert "10 credits" in billing.text
    assert "EUR 2.99" in billing.text

    pending = client.get("/billing/payment-pending")
    assert pending.status_code == 200
    assert "Payment pending" in pending.text

    for path in ["/terms-and-conditions", "/privacy-policy", "/refund-policy"]:
        response = client.get(path)
        assert response.status_code == 200
        assert "Final legal text should be reviewed" in response.text

    self_hosting = client.get("/self-hosting")
    assert self_hosting.status_code == 200
    assert "Run EPUB Translate with Docker Compose." in self_hosting.text

    pricing = client.get("/pricing")
    assert pricing.status_code == 200
    assert "Simple credits for book translation." in pricing.text
    assert "Recommended" in pricing.text


def test_local_mode_hides_public_pricing_and_billing(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "environment", "local")

    home = client.get("/", follow_redirects=False)
    assert home.status_code == 303
    assert home.headers["location"] == "/login"

    pricing = client.get("/pricing", follow_redirects=False)
    assert pricing.status_code == 303
    assert pricing.headers["location"] == "/login"

    register_user(client, email="local@example.com")
    user = db_session.query(User).filter_by(email="local@example.com").one()
    assert user.credit_balance == 0

    jobs = client.get("/jobs")
    assert jobs.status_code == 200
    assert "Local" in jobs.text
    assert "Payment disabled" in jobs.text
    assert "Buy credits" not in jobs.text
    assert "Available credits" not in jobs.text

    billing = client.get("/billing", follow_redirects=False)
    assert billing.status_code == 303
    assert billing.headers["location"] == "/jobs"


def test_checkout_requires_login_and_rejects_invalid_package(client):
    response = client.post(
        "/billing/checkout",
        data={"package_key": "credits_10", "csrf_token": "missing"},
        follow_redirects=False,
    )
    assert response.status_code in {303, 401}

    register_user(client)
    billing = client.get("/billing")
    csrf_token = extract_csrf_token(billing.text)
    invalid = client.post(
        "/billing/checkout",
        data={"package_key": "not_real", "csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert invalid.status_code == 400
    assert "Unknown credit package." in invalid.text


def test_checkout_redirects_to_paddle_url(client, monkeypatch):
    register_user(client)
    monkeypatch.setattr("app.api.routes.create_checkout_url", lambda user_id, package_key: "https://checkout.example.test/pay")

    billing = client.get("/billing")
    csrf_token = extract_csrf_token(billing.text)
    response = client.post(
        "/billing/checkout",
        data={"package_key": "credits_10", "csrf_token": csrf_token},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "https://checkout.example.test/pay"


def test_paddle_webhook_rejects_invalid_signature(client, monkeypatch):
    monkeypatch.setattr(settings, "paddle_webhook_secret", "secret")
    raw_body = b'{"event_type":"transaction.completed"}'

    response = client.post("/webhooks/paddle", content=raw_body, headers={"Paddle-Signature": "ts=1;h1=bad"})

    assert response.status_code == 400


def test_paddle_webhook_adds_credits_once(client, db_session, monkeypatch):
    register_user(client)
    user = db_session.query(User).filter_by(email="billing@example.com").one()
    monkeypatch.setattr(settings, "paddle_webhook_secret", "secret")
    payload = {
        "event_id": "evt_123",
        "event_type": "transaction.completed",
        "data": {
            "id": "txn_123",
            "status": "completed",
            "currency_code": "EUR",
            "custom_data": {"user_id": str(user.id), "package_key": "credits_50"},
            "details": {"totals": {"grand_total": "799", "currency_code": "EUR"}},
        },
    }
    raw_body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = {"Paddle-Signature": sign_paddle_payload(raw_body, "secret")}

    first = client.post("/webhooks/paddle", content=raw_body, headers=headers)
    second = client.post("/webhooks/paddle", content=raw_body, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    db_session.refresh(user)
    assert user.credit_balance == 51
    purchases = db_session.query(CreditTransaction).filter_by(
        user_id=user.id,
        transaction_type=CreditTransactionType.PURCHASE,
    ).all()
    assert len(purchases) == 1
    assert purchases[0].credit_amount == 50
    assert purchases[0].paddle_event_id == "evt_123"


def test_failed_job_refunds_only_after_delay(db_session, monkeypatch):
    monkeypatch.setattr(settings, "refund_delay_minutes", 10)
    user = User(email="refund@example.com", password_hash="hash", tier=UserTier.FREE, credit_balance=20)
    db_session.add(user)
    db_session.flush()
    job = Job(
        user_id=user.id,
        user_tier=user.tier,
        status=JobStatus.UPLOADED,
        original_filename="book.epub",
        stored_filename="stored.epub",
        file_size_bytes=123,
        translator_provider="gemini",
        source_language="English",
        target_language="Serbian Latin",
        progress={"stage": "uploaded"},
    )
    db_session.add(job)
    db_session.flush()
    spend_credits_for_job(db_session, user=user, job=job, credits=10)
    db_session.commit()
    db_session.refresh(user)
    assert user.credit_balance == 10

    update_job_status(db_session, job, JobStatus.FAILED, error_message="failed", progress={"stage": "failed"})
    assert find_refundable_failed_jobs(db_session) == []

    job.failed_at = datetime.now(timezone.utc) - timedelta(minutes=11)
    db_session.add(job)
    db_session.commit()

    refundable = find_refundable_failed_jobs(db_session)
    assert [item.id for item in refundable] == [job.id]
    refund = refund_failed_job(db_session, refundable[0])
    db_session.commit()
    db_session.refresh(user)
    db_session.refresh(job)
    assert refund is not None
    assert user.credit_balance == 20
    assert job.refunded_at is not None
    assert refund_failed_job(db_session, job) is None


def test_completed_job_does_not_refund(db_session):
    user = User(email="complete@example.com", password_hash="hash", tier=UserTier.FREE, credit_balance=20)
    db_session.add(user)
    db_session.flush()
    job = Job(
        user_id=user.id,
        user_tier=user.tier,
        status=JobStatus.UPLOADED,
        original_filename="book.epub",
        stored_filename="complete.epub",
        file_size_bytes=123,
        translator_provider="gemini",
        source_language="English",
        target_language="Serbian Latin",
        progress={"stage": "uploaded"},
    )
    db_session.add(job)
    db_session.flush()
    spend_credits_for_job(db_session, user=user, job=job, credits=10)
    update_job_status(db_session, job, JobStatus.COMPLETED, progress={"stage": "completed"})

    assert find_refundable_failed_jobs(db_session) == []
