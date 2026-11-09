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
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer, TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken

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


class AuthView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]

    def get_authenticate_header(self, request):
        # Makes DRF answer token/credential failures with 401 + WWW-Authenticate, not 403.
        return 'Bearer realm="api"'


class LoginView(AuthView):
    """POST {email, password} -> {access}; the refresh token is set as a cookie."""

    @extend_schema(request=TokenObtainPairSerializer, responses=AccessResponse)
    def post(self, request):
        serializer = TokenObtainPairSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)  # wrong credentials -> 401
        response = Response({"access": serializer.validated_data["access"]})
        set_refresh_cookie(response, serializer.validated_data["refresh"])
        return response


class RefreshView(AuthView):
    """Exchange the refresh cookie for a new access token and a rotated refresh token."""

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
