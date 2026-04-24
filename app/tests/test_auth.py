from __future__ import annotations

from app.tests.helpers import extract_csrf_token


def test_register_login_and_protected_jobs_page(client):
    response = client.get("/register")
    csrf_token = extract_csrf_token(response.text)
    response = client.post(
        "/register",
        data={"email": "reader@example.com", "password": "strongpass123", "csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/jobs"

    jobs_response = client.get("/jobs")
    assert jobs_response.status_code == 200
    assert "Your jobs" in jobs_response.text

    logout_page = client.get("/jobs")
    csrf_token = extract_csrf_token(logout_page.text)
    logout = client.post("/logout", data={"csrf_token": csrf_token}, follow_redirects=False)
    assert logout.status_code == 303

    login_page = client.get("/login")
    csrf_token = extract_csrf_token(login_page.text)
    login = client.post(
        "/login",
        data={"email": "reader@example.com", "password": "strongpass123", "csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert login.status_code == 303
    assert login.headers["location"] == "/jobs"
