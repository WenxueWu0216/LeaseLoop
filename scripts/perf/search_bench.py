"""Standalone benchmark for prospect search: plain B-tree indexes vs pg_trgm GIN indexes.

Builds a table shaped like crm_prospect (same searched columns and list indexes), seeds
100,000 rows over 4 orgs the way seed_demo does, and EXPLAIN ANALYZEs the SQL Django
generates for ?q= (UPPER(col::text) LIKE UPPER(%s) on 4 columns, scoped to one org).

Usage: BENCH_DSN="dbname=bench ..." python scripts/perf/search_bench.py plans.txt
"""

import os
import random
import re
import statistics
import sys
import time
from datetime import UTC, datetime, timedelta

import psycopg
from faker import Faker

# A scratch database: the script drops and recreates a table named "prospect".
DSN = os.environ.get("BENCH_DSN", "dbname=bench user=bench password=bench host=localhost")
ROWS, ORGS = 100_000, 4
TERMS = ["smith", "john", "example.com", "201555", "zz"]
RUNS = 15

SETUP = """
DROP TABLE IF EXISTS prospect;
CREATE TABLE prospect (
  id bigserial PRIMARY KEY,
  organization_id bigint NOT NULL,
  first_name varchar(100) NOT NULL,
  last_name varchar(100) NOT NULL,
  email varchar(254) NOT NULL,
  phone varchar(32) NOT NULL,
  status varchar(20) NOT NULL,
  created_at timestamptz NOT NULL
);
"""
BTREE = """
CREATE INDEX p_org ON prospect (organization_id);
CREATE INDEX p_org_created_id ON prospect (organization_id, created_at DESC, id DESC);
CREATE INDEX p_org_status_created ON prospect (organization_id, status, created_at DESC);
"""
TRGM = """
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX p_first_trgm ON prospect USING gin (UPPER(first_name) gin_trgm_ops);
CREATE INDEX p_last_trgm ON prospect USING gin (UPPER(last_name) gin_trgm_ops);
CREATE INDEX p_email_trgm ON prospect USING gin (UPPER(email) gin_trgm_ops);
CREATE INDEX p_phone_trgm ON prospect USING gin (UPPER(phone) gin_trgm_ops);
"""
WHERE = (
    "organization_id = 1 AND (UPPER(first_name::text) LIKE UPPER(%(p)s)"
    " OR UPPER(last_name::text) LIKE UPPER(%(p)s) OR UPPER(email::text) LIKE UPPER(%(p)s)"
    " OR UPPER(phone::text) LIKE UPPER(%(p)s))"
)
COUNT_SQL = f"SELECT COUNT(*) FROM prospect WHERE {WHERE}"
PAGE_SQL = f"SELECT id FROM prospect WHERE {WHERE} ORDER BY created_at DESC, id DESC LIMIT 25"


def seed(cur):
    base = datetime(2026, 1, 1, tzinfo=UTC)
    rng, fake = random.Random(42), Faker()
    Faker.seed(42)
    firsts = [fake.first_name() for _ in range(1500)]
    lasts = [fake.last_name() for _ in range(1500)]
    statuses = ["NEW", "CONTACTED", "TOUR_SCHEDULED", "TOURED", "APPLIED", "LEASED", "LOST"]
    with cur.copy(
        "COPY prospect (organization_id, first_name, last_name, email, phone, status, created_at)"
        " FROM STDIN"
    ) as cp:
        for i in range(ROWS):
            f, last = rng.choice(firsts), rng.choice(lasts)
            cp.write_row(
                (
                    i % ORGS + 1,
                    f,
                    last,
                    f"{f}.{last}{rng.randint(1, 9999)}@example.com".lower(),
                    f"+1{rng.randint(2012000000, 9899999999)}",
                    rng.choice(statuses),
                    base + timedelta(seconds=rng.randint(0, 27_000_000)),
                )
            )


def explain_ms(cur, sql, term):
    cur.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) " + sql, {"p": f"%{term}%"})
    lines = [r[0] for r in cur.fetchall()]
    ms = float(re.search(r"Execution Time: ([\d.]+)", lines[-1]).group(1))
    return ms, lines


def measure(cur, label, out):
    out.write(f"\n===== {label} =====\n")
    results = {}
    for term in TERMS:
        cur.execute(COUNT_SQL, {"p": f"%{term}%"})
        matches = cur.fetchone()[0]
        for _ in range(3):  # warm cache
            explain_ms(cur, COUNT_SQL, term)
        count_ms = [explain_ms(cur, COUNT_SQL, term)[0] for _ in range(RUNS)]
        page_ms = [explain_ms(cur, PAGE_SQL, term)[0] for _ in range(RUNS)]
        results[term] = (matches, statistics.median(count_ms), statistics.median(page_ms))
        _, plan = explain_ms(cur, COUNT_SQL, term)
        out.write(f"\n-- q={term!r}: {matches} matches; COUNT plan:\n" + "\n".join(plan) + "\n")
        _, plan = explain_ms(cur, PAGE_SQL, term)
        out.write(f"-- q={term!r}: page plan:\n" + "\n".join(plan) + "\n")
    return results


def insert_ms(cur, n=1000):
    rows = [(1, "Ann", "Lee", f"ann.lee{i}@example.com", "+12015550000", "NEW") for i in range(n)]
    t = time.perf_counter()
    cur.executemany(
        "INSERT INTO prospect (organization_id, first_name, last_name, email, phone, status,"
        " created_at) VALUES (%s,%s,%s,%s,%s,%s, now())",
        rows,
    )
    ms = (time.perf_counter() - t) * 1000
    cur.execute("DELETE FROM prospect WHERE email LIKE 'ann.lee%%@example.com'")
    return ms


def main(plan_path):
    with (
        psycopg.connect(DSN, autocommit=True) as conn,
        conn.cursor() as cur,
        open(plan_path, "w") as out,
    ):
        cur.execute(SETUP)
        seed(cur)
        cur.execute(BTREE)
        cur.execute("VACUUM ANALYZE prospect")
        cur.execute("SELECT version()")
        out.write(cur.fetchone()[0] + "\n")
        before = measure(cur, "B-tree indexes only (current main)", out)
        ins_before = statistics.median(insert_ms(cur) for _ in range(5))
        cur.execute(TRGM)
        cur.execute("VACUUM ANALYZE prospect")
        after = measure(cur, "With pg_trgm GIN indexes on UPPER(col)", out)
        ins_after = statistics.median(insert_ms(cur) for _ in range(5))
        cur.execute(
            "SELECT pg_size_pretty(sum(pg_relation_size(indexrelid))) FROM pg_index"
            " WHERE indexrelid::regclass::text LIKE '%%trgm'"
        )
        trgm_size = cur.fetchone()[0]

    print(
        f"{'q':<14}{'matches':>8}{'COUNT before':>14}{'COUNT after':>13}"
        f"{'page before':>13}{'page after':>12}"
    )
    for term in TERMS:
        m, cb, pb = before[term]
        _, ca, pa = after[term]
        print(f"{term:<14}{m:>8}{cb:>12.2f}ms{ca:>11.2f}ms{pb:>11.2f}ms{pa:>10.2f}ms")
    print(f"insert 1,000 rows: {ins_before:.1f} ms before, {ins_after:.1f} ms after")
    print(f"trigram index size: {trgm_size}")


if __name__ == "__main__":
    main(sys.argv[1])
