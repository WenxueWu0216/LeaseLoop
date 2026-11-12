"""Rate limits.

Counters live in the shared cache (Redis in production) so every gunicorn worker and
host counts against the same budget. The client IP comes from DRF's get_ident, which
trusts X-Forwarded-For only for the number of proxies in REST_FRAMEWORK["NUM_PROXIES"];
with the default of 0 a client can't pick its own IP by sending that header.
"""

import logging

from rest_framework.throttling import AnonRateThrottle, SimpleRateThrottle, UserRateThrottle

logger = logging.getLogger(__name__)


class FailOpenMixin:
    """If the cache is down, log and let the request through.

    Losing rate limits for the length of a Redis outage is better than turning every
    API request into a 500.
    """

    def allow_request(self, request, view):
        try:
            return super().allow_request(request, view)
        except Exception:
            logger.exception("throttle cache unavailable; allowing request (%s)", self.scope)
            return True


class AnonThrottle(FailOpenMixin, AnonRateThrottle):
    pass


class UserThrottle(FailOpenMixin, UserRateThrottle):
    pass


class IPThrottle(FailOpenMixin, SimpleRateThrottle):
    """Keyed by client IP whether or not the request is authenticated."""

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class LoginIPThrottle(IPThrottle):
    scope = "login_ip"


class RefreshIPThrottle(IPThrottle):
    scope = "refresh_ip"


class LoginUsernameThrottle(FailOpenMixin, SimpleRateThrottle):
    """Caps attempts on one account however many IPs they come from."""

    scope = "login_user"

    def get_cache_key(self, request, view):
        email = request.data.get("email")
        if not isinstance(email, str) or not email.strip():
            return None  # nothing to guess against; the IP throttle still applies
        return self.cache_format % {"scope": self.scope, "ident": email.strip().lower()}
