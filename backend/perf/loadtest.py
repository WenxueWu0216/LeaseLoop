"""Fixed-concurrency HTTP load test for the key read endpoints.

For each endpoint, ``--concurrency`` workers share one ``httpx.AsyncClient`` and
issue ``--requests`` GETs as fast as responses come back (closed loop). Reports
p50/p95/p99 latency, throughput and errors per endpoint, as a table and JSON.

    python perf/loadtest.py --base http://127.0.0.1:8000 \\
        --token <manager token> --agent-token <agent token> \\
        --concurrency 10 --requests 2000
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import statistics
import time

import httpx


def pct(sorted_ms: list[float], p: float) -> float:
    """Nearest-rank percentile."""
    k = max(0, min(len(sorted_ms) - 1, round(p / 100 * len(sorted_ms) + 0.5) - 1))
    return sorted_ms[k]


async def run_endpoint(base, token, paths, concurrency, total, warmup) -> dict:
    headers = {"Authorization": f"Token {token}"}
    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    path_cycle = itertools.cycle(paths)
    latencies: list[float] = []
    errors = 0
    async with httpx.AsyncClient(
        base_url=base, headers=headers, limits=limits, timeout=30
    ) as client:
        for _ in range(warmup):
            (await client.get(next(path_cycle))).raise_for_status()
        remaining = total
        lock = asyncio.Lock()

        async def worker():
            nonlocal remaining, errors
            while True:
                async with lock:
                    if remaining <= 0:
                        return
                    remaining -= 1
                    path = next(path_cycle)
                t0 = time.perf_counter()
                try:
                    r = await client.get(path)
                    ok = r.status_code == 200
                except httpx.HTTPError:
                    ok = False
                ms = (time.perf_counter() - t0) * 1000
                if ok:
                    latencies.append(ms)
                else:
                    errors += 1

        t_start = time.perf_counter()
        await asyncio.gather(*(worker() for _ in range(concurrency)))
        wall = time.perf_counter() - t_start
    latencies.sort()
    return {
        "requests": total,
        "errors": errors,
        "concurrency": concurrency,
        "p50_ms": round(pct(latencies, 50), 1),
        "p95_ms": round(pct(latencies, 95), 1),
        "p99_ms": round(pct(latencies, 99), 1),
        "mean_ms": round(statistics.fmean(latencies), 1),
        "rps": round(total / wall, 1),
    }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--token", required=True, help="manager API token")
    ap.add_argument("--agent-token", help="leasing-agent API token (agent-scoped list)")
    ap.add_argument("--concurrency", type=int, default=10)
    ap.add_argument("--requests", type=int, default=2000)
    ap.add_argument("--warmup", type=int, default=50)
    ap.add_argument("--only", help="comma-separated endpoint names to run")
    ap.add_argument("--json", help="write results to this file")
    args = ap.parse_args()

    async with httpx.AsyncClient(
        base_url=args.base, headers={"Authorization": f"Token {args.token}"}
    ) as c:
        first = (await c.get("/api/prospects/")).json()
        count = first["count"]
        ids = [p["id"] for p in first["results"]]
        last_page = (count + 24) // 25

    endpoints = {
        "prospects_list": (args.token, ["/api/prospects/"]),
        "prospects_list_page_2_to_50": (
            args.token,
            [f"/api/prospects/?page={n}" for n in range(2, 51)],
        ),
        "prospects_list_deep_page": (args.token, [f"/api/prospects/?page={last_page // 2}"]),
        "prospect_detail": (args.token, [f"/api/prospects/{i}/" for i in ids]),
        "tours_list": (args.token, ["/api/tours/"]),
        "applications_list": (args.token, ["/api/applications/"]),
        "conversations_list": (args.token, ["/api/conversations/"]),
    }
    if args.agent_token:
        endpoints["prospects_list_as_agent"] = (args.agent_token, ["/api/prospects/"])
    if args.only:
        wanted = set(args.only.split(","))
        endpoints = {k: v for k, v in endpoints.items() if k in wanted}

    results = {"prospect_count": count, "endpoints": {}}
    print(f"prospects={count}  concurrency={args.concurrency}  requests/endpoint={args.requests}")
    print(f"{'endpoint':32} {'p50':>8} {'p95':>8} {'p99':>8} {'req/s':>8} {'errors':>7}")
    for name, (token, paths) in endpoints.items():
        r = await run_endpoint(
            args.base, token, paths, args.concurrency, args.requests, args.warmup
        )
        results["endpoints"][name] = r
        print(
            f"{name:32} {r['p50_ms']:>8} {r['p95_ms']:>8} {r['p99_ms']:>8}"
            f" {r['rps']:>8} {r['errors']:>7}"
        )
    if args.json:
        with open(args.json, "w") as fh:
            json.dump(results, fh, indent=2)


if __name__ == "__main__":
    asyncio.run(main())
