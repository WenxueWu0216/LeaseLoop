"""Sequential page-load probe against a running server.

For each endpoint: N timed requests (after warm-up), reporting p50/p95 client
latency, server DB time and the X-DB-Query-Count header. Stdlib only.

    python scripts/perf/probe.py --base http://localhost:8000 --runs 30
"""

import argparse
import json
import statistics
import time
import urllib.request


def login(base, email, password):
    req = urllib.request.Request(
        f"{base}/api/auth/login/",
        data=json.dumps({"username": email, "password": password}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)["token"]


def fetch(base, path, token):
    req = urllib.request.Request(f"{base}{path}", headers={"Authorization": f"Token {token}"})
    start = time.perf_counter()
    with urllib.request.urlopen(req) as resp:
        body = resp.read()
        elapsed = (time.perf_counter() - start) * 1000
        timing = dict(
            part.strip().split(";dur=") for part in resp.headers["Server-Timing"].split(",")
        )
        return elapsed, int(resp.headers["X-DB-Query-Count"]), float(timing["db"]), body


def pct(values, p):
    values = sorted(values)
    return values[min(len(values) - 1, round(p / 100 * (len(values) - 1)))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--runs", type=int, default=30)
    ap.add_argument("--password", default="demo1234!")
    args = ap.parse_args()

    manager = login(args.base, "manager@org1.demo", args.password)
    agent = login(args.base, "agent1@org1.demo", args.password)
    _, _, _, body = fetch(args.base, "/api/prospects/?page_size=1", manager)
    prospect_id = json.loads(body)["results"][0]["id"]

    cases = [
        ("Prospect list (manager, page 1)", "/api/prospects/", manager),
        ("Prospect list, status=CONTACTED", "/api/prospects/?status=CONTACTED", manager),
        ("Prospect list (agent scope)", "/api/prospects/", agent),
        ("Prospect list, page 500", "/api/prospects/?page=500", manager),
        ("Prospect search q=smith", "/api/prospects/?q=smith", manager),
        ("Prospect detail", f"/api/prospects/{prospect_id}/", manager),
        ("Tours, upcoming", "/api/tours/?status=SCHEDULED", manager),
        ("Units, available", "/api/units/?status=AVAILABLE", manager),
        ("Conversations (inbox)", "/api/conversations/", manager),
    ]
    print("| Endpoint | Queries | p50 ms | p95 ms | DB ms (p50) |")
    print("|---|---:|---:|---:|---:|")
    for label, path, token in cases:
        for _ in range(3):
            fetch(args.base, path, token)
        lat, queries, db = [], set(), []
        for _ in range(args.runs):
            ms, q, db_ms, _ = fetch(args.base, path, token)
            lat.append(ms)
            queries.add(q)
            db.append(db_ms)
        q_str = "/".join(str(q) for q in sorted(queries))
        print(
            f"| {label} | {q_str} | {pct(lat, 50):.1f} | {pct(lat, 95):.1f} | "
            f"{statistics.median(db):.1f} |"
        )


if __name__ == "__main__":
    main()
