"""JWT login, refresh and logout.

The access token (15 min) is returned in the response body and kept in memory by
the browser client. The refresh token (7 days) only ever travels in an HttpOnly,
SameSite=Strict cookie scoped to /api/auth/, so scripts in the page cannot read it
and other sites cannot make the browser send it. Every refresh rotates it and
blacklists the old one; logout blacklists the current one.
"""

from contextlib import suppress

from django.conf import settings
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.parsers import JSONParser
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer, TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from apps.audit.services import record_login
from apps.core.throttling import (
    AnonThrottle,
    LoginIPThrottle,
    LoginUsernameThrottle,
    RefreshIPThrottle,
)

COOKIE_PATH = "/api/auth/"
AccessResponse = inline_serializer("AccessResponse", {"access": serializers.CharField()})


def set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        settings.JWT_REFRESH_COOKIE,
        token,
        max_age=int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds()),
        httponly=True,
        secure=settings.JWT_REFRESH_COOKIE_SECURE,
        samesite="Strict",
        path=COOKIE_PATH,
    )


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(settings.JWT_REFRESH_COOKIE, path=COOKIE_PATH, samesite="Strict")


def refresh_token_from(request) -> str | None:
    # Browsers send the cookie; non-browser clients may post {"refresh": ...}.
    return request.COOKIES.get(settings.JWT_REFRESH_COOKIE) or request.data.get("refresh")


class TrustedOrigin(BasePermission):
    """CSRF defence for endpoints that act on the refresh cookie.

    SameSite=Strict keeps other *sites* from sending the cookie, but a sibling
    subdomain counts as the same site. Browsers send Origin on every POST, so a POST
    from any origin other than ours (or CSRF_TRUSTED_ORIGINS) is refused. Requests
    without Origin come from non-browser clients, which carry no ambient cookies.
    """

    message = "Origin not allowed."

    def has_permission(self, request, view) -> bool:
        origin = request.headers.get("Origin")
        if origin is None:
            return True
        own = f"{request.scheme}://{request.get_host()}"
        return origin == own or origin in settings.CSRF_TRUSTED_ORIGINS


class AuthView(APIView):
    authentication_classes: list = []
    permission_classes = [TrustedOrigin]
    # JSON only: an HTML form can't send it, and a cross-origin fetch sending it needs a
    # CORS preflight, which is refused for origins not on the allowlist.
    parser_classes = [JSONParser]

    def get_authenticate_header(self, request):
        # Makes DRF answer token/credential failures with 401 + WWW-Authenticate, not 403.
        return 'Bearer realm="api"'


class LoginView(AuthView):
    """POST {email, password} -> {access}; the refresh token is set as a cookie."""

    # Password guessing: 5/min per IP and 5/min per account (any IP).
    throttle_classes = [LoginIPThrottle, LoginUsernameThrottle]

    @extend_schema(request=TokenObtainPairSerializer, responses=AccessResponse)
    def post(self, request):
        serializer = TokenObtainPairSerializer(data=request.data, context={"request": request})
        try:
            serializer.is_valid(raise_exception=True)
        except AuthenticationFailed:  # wrong password, unknown or inactive account -> 401
            record_login(request, success=False, email=str(request.data.get("email", "")))
            raise
        record_login(request, success=True, email=serializer.user.email, user=serializer.user)
        response = Response({"access": serializer.validated_data["access"]})
        set_refresh_cookie(response, serializer.validated_data["refresh"])
        return response


class RefreshView(AuthView):
    """Exchange the refresh cookie for a new access token and a rotated refresh token."""

    # Keyed by IP only: the user id inside a refresh token isn't trusted until the
    # token is verified, so keying on it would let anyone lock out any user.
    throttle_classes = [RefreshIPThrottle]

    @extend_schema(request=None, responses=AccessResponse)
    def post(self, request):
        token = refresh_token_from(request)
        if not token:
            raise InvalidToken("No refresh token.")
        serializer = TokenRefreshSerializer(data={"refresh": token})
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as exc:  # expired, blacklisted (reused) or tampered
            raise InvalidToken(exc.args[0]) from exc
        response = Response({"access": serializer.validated_data["access"]})
        set_refresh_cookie(response, serializer.validated_data["refresh"])
        return response


class LogoutView(AuthView):
    """Blacklist the refresh token and clear its cookie. Idempotent."""

    throttle_classes = [AnonThrottle]

    @extend_schema(request=None, responses={204: None})
    def post(self, request):
        token = refresh_token_from(request)
        if token:
            # Already expired or blacklisted: nothing left to revoke.
            with suppress(TokenError):
                RefreshToken(token).blacklist()
        response = Response(status=status.HTTP_204_NO_CONTENT)
        clear_refresh_cookie(response)
        return response
