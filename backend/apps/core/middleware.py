import logging
import time
import uuid

from django.conf import settings
from django.db import connection

logger = logging.getLogger("leaseloop.request")


class QueryCounter:
    """execute_wrapper hook: counts queries and DB time without needing DEBUG=True."""

    def __init__(self) -> None:
        self.count = 0
        self.seconds = 0.0

    def __call__(self, execute, sql, params, many, context):
        start = time.perf_counter()
        try:
            return execute(sql, params, many, context)
        finally:
            self.count += 1
            self.seconds += time.perf_counter() - start


class RequestMetricsMiddleware:
    """Per-request query count, DB time and latency, emitted as one structured log line.

    Also echoes them back as headers (X-Request-ID, X-DB-Query-Count, Server-Timing)
    so load tests and the browser devtools can see them.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.request_id = request_id
        counter = QueryCounter()
        start = time.perf_counter()
        with connection.execute_wrapper(counter):
            response = self.get_response(request)
        total_ms = (time.perf_counter() - start) * 1000
        db_ms = counter.seconds * 1000

        response["X-Request-ID"] = request_id
        response["X-DB-Query-Count"] = str(counter.count)
        response["Server-Timing"] = f"db;dur={db_ms:.1f}, total;dur={total_ms:.1f}"

        membership = getattr(request, "_membership", None)
        user = getattr(request, "user", None)
        fields = {
            "request_id": request_id,
            "method": request.method,
            "path": request.path,
            "status": response.status_code,
            "duration_ms": round(total_ms, 1),
            "db_ms": round(db_ms, 1),
            "db_queries": counter.count,
            "org_id": membership.organization_id if membership else None,
            "user_id": user.pk if user is not None and user.is_authenticated else None,
        }
        slow = (
            total_ms > settings.SLOW_REQUEST_MS or counter.count > settings.MAX_QUERIES_PER_REQUEST
        )
        logger.log(logging.WARNING if slow else logging.INFO, "request", extra={"fields": fields})
        return response
