from datetime import timedelta

import jwt
import pytest
from django.conf import settings
from django.utils import timezone
from freezegun import freeze_time
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

pytestmark = pytest.mark.django_db
COOKIE = settings.JWT_REFRESH_COOKIE


def login(client, user, password="pass1234!"):
    return client.post(
        "/api/auth/login/", {"email": user.email, "password": password}, format="json"
    )


def bearer(token):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def test_login_returns_short_lived_access_and_httponly_refresh_cookie(agent):
    client = APIClient()
    resp = login(client, agent)
    assert resp.status_code == 200 and set(resp.data) == {"access"}  # refresh never in the body
    claims = jwt.decode(resp.data["access"], options={"verify_signature": False})
    assert claims["exp"] - claims["iat"] == 15 * 60
    cookie = resp.cookies[COOKIE]
    assert cookie["httponly"] and cookie["samesite"] == "Strict"
    assert cookie["path"] == "/api/auth/"
    assert int(cookie["max-age"]) == 7 * 24 * 3600
    assert bearer(resp.data["access"]).get("/api/auth/me/").status_code == 200


def test_wrong_password_is_401_and_sets_no_cookie(agent):
    resp = login(APIClient(), agent, password="wrong")
    assert resp.status_code == 401 and COOKIE not in resp.cookies


def test_expired_access_token_is_rejected(agent):
    token = AccessToken.for_user(agent)
    token.set_exp(from_time=timezone.now() - timedelta(minutes=16))  # expired a minute ago
    resp = bearer(str(token)).get("/api/auth/me/")
    assert resp.status_code == 401 and resp.data["code"] == "token_not_valid"


def test_access_token_stops_working_after_15_minutes(agent):
    with freeze_time() as clock:
        access = login(APIClient(), agent).data["access"]
        assert bearer(access).get("/api/auth/me/").status_code == 200
        clock.tick(timedelta(minutes=15, seconds=1))
        assert bearer(access).get("/api/auth/me/").status_code == 401


def test_refresh_rotates_and_reused_refresh_token_is_rejected(agent):
    client = APIClient()
    login(client, agent)
    first_refresh = client.cookies[COOKIE].value

    resp = client.post("/api/auth/refresh/")
    assert resp.status_code == 200 and "access" in resp.data
    second_refresh = resp.cookies[COOKIE].value
    assert second_refresh != first_refresh  # rotated
    assert bearer(resp.data["access"]).get("/api/auth/me/").status_code == 200

    # Replaying the old refresh token (e.g. a stolen copy) fails: it was blacklisted.
    replay = APIClient()
    replay.cookies[COOKIE] = first_refresh
    resp = replay.post("/api/auth/refresh/")
    assert resp.status_code == 401 and resp.data["code"] == "token_not_valid"
    # The rotated one keeps working.
    assert client.post("/api/auth/refresh/").status_code == 200


def test_logout_revokes_refresh_token_and_clears_cookie(agent):
    client = APIClient()
    login(client, agent)
    refresh = client.cookies[COOKIE].value
    resp = client.post("/api/auth/logout/")
    assert resp.status_code == 204 and resp.cookies[COOKIE].value == ""
    attacker = APIClient()
    attacker.cookies[COOKIE] = refresh
    assert attacker.post("/api/auth/refresh/").status_code == 401
    assert APIClient().post("/api/auth/logout/").status_code == 204  # idempotent


def test_refresh_without_token_or_with_garbage_is_401():
    assert APIClient().post("/api/auth/refresh/").status_code == 401
    client = APIClient()
    client.cookies[COOKIE] = "not-a-jwt"
    assert client.post("/api/auth/refresh/").status_code == 401


def test_refresh_token_expires_after_7_days(agent):
    with freeze_time() as clock:
        client = APIClient()
        login(client, agent)
        clock.tick(timedelta(days=7, seconds=1))
        assert client.post("/api/auth/refresh/").status_code == 401


def test_inactive_user_cannot_refresh(agent):
    client = APIClient()
    login(client, agent)
    agent.is_active = False
    agent.save()
    assert client.post("/api/auth/refresh/").status_code == 401


def test_legacy_drf_token_scheme_is_not_accepted(agent):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Token 0123456789abcdef0123456789abcdef01234567")
    assert client.get("/api/prospects/").status_code == 401


def test_session_auth_still_works_for_admin_and_swagger(db):
    from apps.accounts.models import User

    admin = User.objects.create_superuser("root@example.com", "pass1234!")
    client = APIClient()
    assert client.get("/api/docs/").status_code in (401, 403)
    assert client.get("/api/schema/").status_code in (401, 403)
    client.force_login(admin)
    assert client.get("/admin/").status_code == 200
    assert client.get("/api/docs/").status_code == 200
    assert client.get("/api/schema/").status_code == 200
