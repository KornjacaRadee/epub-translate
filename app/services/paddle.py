from __future__ import annotations

import hmac
import json
from hashlib import sha256
from typing import Any
from uuid import UUID

import httpx

from app.core.config import settings
from app.services.credits import CreditPackage, get_credit_package, package_price_id


class PaddleError(RuntimeError):
    pass


def paddle_api_base_url() -> str:
    if settings.paddle_environment == "production":
        return "https://api.paddle.com"
    return "https://sandbox-api.paddle.com"


def parse_paddle_signature_header(header: str) -> dict[str, str]:
    parts: dict[str, str] = {}
    for item in header.split(";"):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        parts[key.strip()] = value.strip()
    return parts


def verify_paddle_signature(raw_body: bytes, signature_header: str | None) -> bool:
    if not settings.paddle_webhook_secret or not signature_header:
        return False
    parts = parse_paddle_signature_header(signature_header)
    timestamp = parts.get("ts")
    received_signature = parts.get("h1")
    if not timestamp or not received_signature:
        return False
    signed_payload = timestamp.encode("utf-8") + b":" + raw_body
    expected_signature = hmac.new(
        settings.paddle_webhook_secret.encode("utf-8"),
        signed_payload,
        sha256,
    ).hexdigest()
    return hmac.compare_digest(expected_signature, received_signature)


def parse_webhook_payload(raw_body: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise PaddleError("Invalid Paddle webhook payload.") from exc
    if not isinstance(payload, dict):
        raise PaddleError("Invalid Paddle webhook payload.")
    return payload


def create_checkout_url(*, user_id: UUID, package_key: str) -> str:
    package = get_credit_package(package_key)
    if not settings.paddle_api_key:
        raise PaddleError("Paddle is not configured.")
    price_id = package_price_id(package)
    if not price_id:
        raise PaddleError("This credit package is not configured.")

    payload = {
        "items": [{"price_id": price_id, "quantity": 1}],
        "custom_data": {
            "user_id": str(user_id),
            "package_key": package.key,
        },
        "checkout": {
            "url": f"{settings.base_url.rstrip('/')}/billing/payment-pending",
        },
    }
    headers = {
        "Authorization": f"Bearer {settings.paddle_api_key}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=30) as client:
        response = client.post(f"{paddle_api_base_url()}/transactions", json=payload, headers=headers)
    if response.status_code >= 400:
        raise PaddleError("Paddle checkout could not be created.")
    data = response.json()
    checkout_url = extract_checkout_url(data)
    if not checkout_url:
        raise PaddleError("Paddle checkout response did not include a checkout URL.")
    return checkout_url


def extract_checkout_url(response_payload: dict[str, Any]) -> str | None:
    data = response_payload.get("data") if isinstance(response_payload.get("data"), dict) else response_payload
    checkout = data.get("checkout") if isinstance(data, dict) else None
    if isinstance(checkout, dict) and isinstance(checkout.get("url"), str):
        return checkout["url"]
    links = data.get("_links") if isinstance(data, dict) else None
    if isinstance(links, dict):
        checkout_link = links.get("checkout")
        if isinstance(checkout_link, dict) and isinstance(checkout_link.get("href"), str):
            return checkout_link["href"]
    return None


def extract_completed_payment(payload: dict[str, Any]) -> dict[str, Any] | None:
    event_type = str(payload.get("event_type") or "")
    if event_type not in {"transaction.completed", "transaction.paid", "transaction.payment_succeeded"}:
        return None
    event_id = str(payload.get("event_id") or payload.get("id") or "")
    data = payload.get("data")
    if not event_id or not isinstance(data, dict):
        raise PaddleError("Paddle webhook is missing required event data.")
    custom_data = data.get("custom_data")
    if not isinstance(custom_data, dict):
        raise PaddleError("Paddle webhook is missing custom data.")
    user_id = custom_data.get("user_id")
    package_key = custom_data.get("package_key")
    if not user_id or not package_key:
        raise PaddleError("Paddle webhook custom data is incomplete.")
    details = data.get("details") if isinstance(data.get("details"), dict) else {}
    totals = details.get("totals") if isinstance(details.get("totals"), dict) else {}
    return {
        "event_id": event_id,
        "user_id": UUID(str(user_id)),
        "package_key": str(package_key),
        "paddle_transaction_id": str(data.get("id")) if data.get("id") else None,
        "payment_amount": str(totals.get("grand_total")) if totals.get("grand_total") is not None else None,
        "currency": str(data.get("currency_code") or totals.get("currency_code") or "") or None,
        "status": str(data.get("status") or event_type),
    }
