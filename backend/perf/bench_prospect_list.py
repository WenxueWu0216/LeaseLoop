"""N+1 benchmark for GET /api/prospects/.

Creates a throwaway test database, seeds a fixed synthetic dataset, then for each
mode reports the SQL query count of one request and the median wall time over
``--runs`` requests (in-process via DRF's APIClient, so no network/server noise).

Modes:
  optimized  the code as it is (select_related + subquery annotations)
  naive      same serializer, but ProspectQuerySet.with_list_data() patched to a
             no-op *inside this process only* -> the "before" N+1 version

    cd backend && .venv/bin/python perf/bench_prospect_list.py --prospects 200 --runs 20
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from contextlib import nullcontext
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.db import connection  # noqa: E402
from django.test.utils import (  # noqa: E402
    CaptureQueriesContext,
    setup_test_environment,
    teardown_test_environment,
)
from rest_framework.test import APIClient  # noqa: E402

from apps.crm import models as crm  # noqa: E402
from apps.crm.seeding import make_context, seed_prospects  # noqa: E402


def naive_patch():
    qs_cls = getattr(crm, "ProspectQuerySet", None)
    if qs_cls is None or not hasattr(qs_cls, "with_list_data"):
        raise SystemExit("naive mode needs ProspectQuerySet.with_list_data (not in this checkout)")
    return mock.patch.object(qs_cls, "with_list_data", lambda self: self)


def measure(client: APIClient, url: str, runs: int, warmup: int = 3) -> dict:
    for _ in range(warmup):
        assert client.get(url).status_code == 200
    with CaptureQueriesContext(connection) as ctx:
        resp = client.get(url)
    # Read now: captured_queries is lazy and request_started resets the query log.
    queries = len(ctx.captured_queries)
    assert resp.status_code == 200, resp.status_code
    rows = len(resp.json()["results"])
    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        r = client.get(url)
        times.append((time.perf_counter() - t0) * 1000)
        assert r.status_code == 200
    return {
        "rows_on_page": rows,
        "queries": queries,
        "median_ms": round(statistics.median(times), 2),
        "min_ms": round(min(times), 2),
        "max_ms": round(max(times), 2),
        "runs": runs,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prospects", type=int, default=200)
    ap.add_argument("--runs", type=int, default=20)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--modes", default="naive,optimized")
    ap.add_argument("--url", default="/api/prospects/")
    args = ap.parse_args()

    setup_test_environment()
    # Own name, so pytest's --reuse-db database is left alone.
    connection.settings_dict.setdefault("TEST", {})["NAME"] = "test_leaseloop_bench"
    old_name = connection.creation.create_test_db(verbosity=0, autoclobber=True)
    try:
        ctx = make_context(slug="bench-org", seed=args.seed)
        totals = seed_prospects(ctx, args.prospects)
        client = APIClient()
        client.force_authenticate(ctx.manager)
        results = {"dataset": totals, "url": args.url}
        for mode in args.modes.split(","):
            patch = naive_patch() if mode == "naive" else nullcontext()
            with patch:
                results[mode] = measure(client, args.url, args.runs)
        print(json.dumps(results, indent=2))
    finally:
        connection.creation.destroy_test_db(old_name, verbosity=0)
        teardown_test_environment()


if __name__ == "__main__":
    main()
