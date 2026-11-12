"""Rate limits on login, refresh and the API as a whole."""

from datetime import timedelta
from unittest import mock

import pytest
from django.utils import timezone
from freezegun import freeze_time
from rest_framework.settings import api_settings
from rest_framework.test import APIClient

from .factories import UserFactory

LOGIN = "/api/auth/login/"
REFRESH = "/api/auth/refresh/"
PASSWORD = "correct-horse-battery"


@pytest.fixture
def user(db):
    u = UserFactory(email="renter.ops@example.com")
    u.set_password(PASSWORD)
    u.save()
    return u


def login(client, email, password="wrong", ip="203.0.113.10", **extra):
    return client.post(
        LOGIN, {"email": email, "password": password}, format="json", REMOTE_ADDR=ip, **extra
    )


def test_sixth_login_attempt_in_a_minute_from_one_ip_is_429(user):
    client = APIClient()
    for _ in range(5):
        assert login(client, user.email).status_code == 401
    resp = login(client, user.email, password=PASSWORD)  # even the right password
    assert resp.status_code == 429
    assert int(resp["Retry-After"]) > 0


def test_per_ip_limit_spans_usernames(user):
    client = APIClient()
    for i in range(5):
        assert login(client, f"guess{i}@example.com").status_code == 401
    assert login(client, "guess5@example.com").status_code == 429


def test_per_username_limit_spans_ips_and_ignores_case(user):
    client = APIClient()
    for i in range(5):
        email = user.email.upper() if i % 2 else user.email
        assert login(client, email, ip=f"198.51.100.{i}").status_code == 401
    assert login(client, f"  {user.email} ", ip="198.51.100.99").status_code == 429
    # Another account from a fresh IP is unaffected.
    assert login(client, "someone.else@example.com", ip="198.51.100.200").status_code == 401


def test_spoofed_x_forwarded_for_does_not_reset_the_ip_budget(user):
    client = APIClient()
    for i in range(5):
        resp = login(client, f"guess{i}@example.com", HTTP_X_FORWARDED_FOR=f"10.0.0.{i}")
        assert resp.status_code == 401
    resp = login(client, "guess5@example.com", HTTP_X_FORWARDED_FOR="10.0.0.99")
    assert resp.status_code == 429


def test_login_budget_resets_after_the_window(user):
    client = APIClient()
    with freeze_time(timezone.now()) as clock:
        for _ in range(5):
            login(client, user.email)
        assert login(client, user.email).status_code == 429
        clock.tick(timedelta(seconds=61))
        assert login(client, user.email, password=PASSWORD).status_code == 200


def test_refresh_is_throttled_per_ip(db):
    client = APIClient()
    limit = int(api_settings.DEFAULT_THROTTLE_RATES["refresh_ip"].split("/")[0])
    for _ in range(limit):
        assert client.post(REFRESH, REMOTE_ADDR="203.0.113.20").status_code == 401
    assert client.post(REFRESH, REMOTE_ADDR="203.0.113.20").status_code == 429
    assert client.post(REFRESH, REMOTE_ADDR="203.0.113.21").status_code == 401


def test_authenticated_api_has_a_per_user_limit(manager_client, monkeypatch):
    monkeypatch.setitem(api_settings.DEFAULT_THROTTLE_RATES, "user", "3/min")
    codes = [manager_client.get("/api/prospects/").status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]


def test_anonymous_endpoints_have_a_per_ip_limit(db, monkeypatch):
    # DRF checks permissions before throttles, so anonymous calls to protected views
    # are refused (401) before reaching a throttle; this applies to AllowAny views.
    monkeypatch.setitem(api_settings.DEFAULT_THROTTLE_RATES, "anon", "2/min")
    client = APIClient()
    codes = [client.post("/api/auth/logout/").status_code for _ in range(3)]
    assert codes == [204, 204, 429]


def test_webhooks_are_not_throttled(db, monkeypatch, settings):
    settings.SENDGRID_INBOUND_TOKEN = "t"
    monkeypatch.setitem(api_settings.DEFAULT_THROTTLE_RATES, "anon", "1/min")
    client = APIClient()
    codes = {
        client.post("/api/webhooks/sendgrid/inbound/?token=bad", {}).status_code for _ in range(3)
    }
    assert 429 not in codes


def test_throttles_fail_open_when_the_cache_is_down(user):
    client = APIClient()
    with mock.patch("django.core.cache.cache.get", side_effect=ConnectionError("redis down")):
        for _ in range(7):
            assert login(client, user.email).status_code == 401
