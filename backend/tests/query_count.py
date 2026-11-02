"""SQL query counting for tests and benchmarks."""

from collections.abc import Callable
from typing import Any

from django.db import connection
from django.test.utils import CaptureQueriesContext


def count_queries(fn: Callable[[], Any]) -> tuple[int, Any, list[str]]:
    """Run ``fn`` and return (query count, its result, the SQL statements).

    The count is read inside the call: ``captured_queries`` is lazy and Django
    resets the query log on every ``request_started`` signal.
    """
    with CaptureQueriesContext(connection) as ctx:
        result = fn()
    sql = [q["sql"] for q in ctx.captured_queries]
    return len(sql), result, sql
