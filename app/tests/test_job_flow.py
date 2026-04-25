from __future__ import annotations

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
    assert response.status_code == 303
    assert response.headers["location"].startswith("/jobs/")
    assert queued

    detail = client.get(response.headers["location"])
    assert detail.status_code == 200
    assert "Upload received" in detail.text
    assert "Preparing the translation job." in detail.text
    assert "progress-bar-indeterminate" in detail.text
