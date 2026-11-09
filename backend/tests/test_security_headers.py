"""Security headers, HTTPS, CORS and CSRF behaviour."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from django.conf import settings
from django.test import override_settings
from rest_framework.test import APIClient

from .factories import UserFactory

pytestmark = pytest.mark.django_db
BACKEND = Path(__file__).resolve().parents[1]


def csp(resp) -> dict[str, str]:
    parts = (p.strip().split(" ", 1) for p in resp["Content-Security-Policy"].split(";"))
    return {p[0]: p[1] if len(p) > 1 else "" for p in parts if p[0]}


def test_api_responses_carry_the_security_headers(manager_client):
    resp = manager_client.get("/api/prospects/")
    assert resp.status_code == 200
    assert resp["X-Content-Type-Options"] == "nosniff"
    assert resp["X-Frame-Options"] == "DENY"
    assert resp["Referrer-Policy"] == "same-origin"
    assert resp["Cross-Origin-Opener-Policy"] == "same-origin"
    policy = csp(resp)
    assert policy["default-src"] == "'self'"
    assert policy["script-src"] == "'self'"
    assert policy["object-src"] == "'none'"
    assert policy["frame-ancestors"] == "'none'"
    assert policy["base-uri"] == "'none'"


def test_error_responses_carry_them_too():
    resp = APIClient().get("/api/prospects/")
    assert resp.status_code == 401
    assert resp["X-Content-Type-Options"] == "nosniff"
    assert "frame-ancestors 'none'" in resp["Content-Security-Policy"]


def test_hsts_is_sent_on_https_only():
    client = APIClient()
    secure = client.get("/api/auth/me/", secure=True)
    assert secure["Strict-Transport-Security"] == "max-age=31536000; includeSubDomains"
    assert "Strict-Transport-Security" not in client.get("/api/auth/me/")


def test_plain_http_is_redirected_to_https():
    with override_settings(SECURE_SSL_REDIRECT=True):
        resp = APIClient().get("/api/auth/me/")
    assert resp.status_code == 301
    assert resp["Location"] == "https://testserver/api/auth/me/"


def test_cookies_are_secure_outside_debug():
    assert settings.DEBUG is False
    assert settings.SESSION_COOKIE_SECURE and settings.CSRF_COOKIE_SECURE
    assert settings.SESSION_COOKIE_HTTPONLY and settings.JWT_REFRESH_COOKIE_SECURE


def test_only_the_docs_page_may_load_from_the_cdn(manager):
    client = APIClient()
    client.force_login(manager)
    docs = client.get("/api/docs/")
    assert docs.status_code == 200
    assert "https://cdn.jsdelivr.net" in csp(docs)["script-src"]
    assert "'unsafe-inline'" not in csp(docs)["script-src"]
    assert "cdn.jsdelivr.net" not in client.get("/api/schema/")["Content-Security-Policy"]


def test_admin_login_page_has_the_strict_policy():
    resp = APIClient().get("/admin/login/")
    assert resp.status_code == 200
    assert csp(resp)["script-src"] == "'self'"
    assert resp["X-Frame-Options"] == "DENY"


# --- CORS --------------------------------------------------------------------------------


def preflight(origin):
    return APIClient().options(
        "/api/prospects/",
        HTTP_ORIGIN=origin,
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET",
        HTTP_ACCESS_CONTROL_REQUEST_HEADERS="authorization",
    )


def test_cors_is_closed_by_default():
    resp = preflight("https://evil.example")
    assert "Access-Control-Allow-Origin" not in resp


@override_settings(CORS_ALLOWED_ORIGINS=["https://partner.example"])
def test_cors_allowlist_admits_only_listed_origins_without_credentials():
    ok = preflight("https://partner.example")
    assert ok["Access-Control-Allow-Origin"] == "https://partner.example"
    assert "Access-Control-Allow-Credentials" not in ok
    assert "Access-Control-Allow-Origin" not in preflight("https://partner.example.evil.com")


# --- CSRF --------------------------------------------------------------------------------


def test_session_authenticated_writes_need_a_csrf_token(manager):
    client = APIClient(enforce_csrf_checks=True)
    client.force_login(manager)
    body = {"first_name": "Csrf", "last_name": "Test"}
    resp = client.post("/api/prospects/", body, format="json")
    assert resp.status_code == 403 and "CSRF" in str(resp.data["detail"])

    client.get("/admin/login/")  # sets the csrftoken cookie
    token = client.cookies["csrftoken"].value
    resp = client.post("/api/prospects/", body, format="json", HTTP_X_CSRFTOKEN=token)
    assert resp.status_code == 201


def test_bearer_requests_need_no_csrf_token(manager):
    from rest_framework_simplejwt.tokens import AccessToken

    client = APIClient(enforce_csrf_checks=True)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(manager)}")
    resp = client.post("/api/prospects/", {"first_name": "A", "last_name": "B"}, format="json")
    assert resp.status_code == 201  # no ambient credential, so nothing to forge


@pytest.fixture
def user(db):
    u = UserFactory(email="origin@example.com")
    u.set_password("pw-123456789")
    u.save()
    return u


def test_auth_endpoints_reject_foreign_origins(user):
    client = APIClient()
    creds = {"email": user.email, "password": "pw-123456789"}
    resp = client.post("/api/auth/login/", creds, format="json", HTTP_ORIGIN="https://evil.example")
    assert resp.status_code == 403
    resp = client.post("/api/auth/refresh/", HTTP_ORIGIN="https://app.evil.example")
    assert resp.status_code == 403
    resp = client.post("/api/auth/logout/", HTTP_ORIGIN="null")
    assert resp.status_code == 403


def test_auth_endpoints_accept_same_origin_and_non_browser_clients(user):
    client = APIClient()
    creds = {"email": user.email, "password": "pw-123456789"}
    resp = client.post("/api/auth/login/", creds, format="json", HTTP_ORIGIN="http://testserver")
    assert resp.status_code == 200
    assert client.post("/api/auth/login/", creds, format="json").status_code == 200


def test_login_rejects_form_encoded_bodies(user):
    # A cross-site <form> can only send form encodings; JSON requires a CORS preflight.
    creds = {"email": user.email, "password": "pw-123456789"}
    resp = APIClient().post("/api/auth/login/", creds)  # multipart, like a form
    assert resp.status_code == 415


# --- secret key ---------------------------------------------------------------------------


@pytest.mark.parametrize("key", [None, "change-me", "short-but-random-91x"])
def test_settings_refuse_a_weak_secret_key_outside_debug(key):
    env = {k: v for k, v in os.environ.items() if k != "DJANGO_SECRET_KEY"}
    env.update(DJANGO_DEBUG="false")
    if key:
        env["DJANGO_SECRET_KEY"] = key
    result = subprocess.run(
        [sys.executable, "-c", "import config.settings"],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "DJANGO_SECRET_KEY must be a random value" in result.stderr


def test_settings_load_with_a_strong_secret_key_outside_debug():
    env = dict(os.environ, DJANGO_DEBUG="false", DJANGO_SECRET_KEY="k3Y-" + "x7Gq9pLm" * 6)
    result = subprocess.run(
        [sys.executable, "-c", "import config.settings"], cwd=BACKEND, env=env, capture_output=True
    )
    assert result.returncode == 0, result.stderr
