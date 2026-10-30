"""Exact percentiles from LOCUST_RAW_CSV, excluding setup requests and warm-up.

python scripts/perf/summarize.py raw.csv --warmup 15
"""

import argparse
import csv
from collections import defaultdict


def pct(values, p):
    values = sorted(values)
    return values[min(len(values) - 1, round(p / 100 * (len(values) - 1)))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("raw")
    ap.add_argument("--warmup", type=float, default=15, help="seconds to drop at the start")
    args = ap.parse_args()

    with open(args.raw) as f:
        rows = [(float(t), name, float(ms), int(err)) for t, name, ms, err in csv.reader(f)]
    t0 = min(r[0] for r in rows) + args.warmup
    rows = [r for r in rows if r[0] >= t0 and not r[1].startswith("setup")]
    duration = max(r[0] for r in rows) - t0
    by_name = defaultdict(list)
    errors = defaultdict(int)
    for _, name, ms, err in rows:
        by_name[name].append(ms)
        errors[name] += err
    by_name["**All endpoints**"] = [r[2] for r in rows]
    errors["**All endpoints**"] = sum(r[3] for r in rows)

    print("| Endpoint | Requests | Errors | p50 ms | p95 ms | p99 ms | req/s |")
    print("|---|---:|---:|---:|---:|---:|---:|")
    for name in sorted(by_name, key=lambda n: (n.startswith("**"), n)):
        v = by_name[name]
        print(
            f"| `{name}` | {len(v)} | {errors[name]} | {pct(v, 50):.0f} | {pct(v, 95):.0f} | "
            f"{pct(v, 99):.0f} | {len(v) / duration:.1f} |".replace("`**", "**").replace(
                "**`", "**"
            )
        )


if __name__ == "__main__":
    main()
