# LeaseLoop

Multi-tenant apartment leasing CRM with an AI leasing assistant. Built with Django + DRF,
PostgreSQL/pgvector, Celery/Redis and React. Work in progress; the full README lands with the final stage.

## Quick start

```bash
cp .env.example .env
./scripts/install-hooks.sh
docker compose up --build
```

API: http://localhost:8000/api/ · OpenAPI docs: http://localhost:8000/api/docs/

## Local development (without Docker)

```bash
cd backend
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python manage.py migrate
.venv/bin/pytest
```

## Performance

All numbers below were measured, not estimated. **The data is synthetic** (Faker names,
`example.com` emails, `555` phone numbers) and **every test ran locally**: client, Django and
PostgreSQL on one machine. Raw outputs are in [`backend/perf/results/`](backend/perf/results/).

**Machine:** Linux container, Intel Xeon @ 2.80 GHz, 4 vCPUs, 15 GiB RAM, no swap.
PostgreSQL 16.15 on the same host (default config), Python 3.12, Django 5.1.4, DRF 3.15.2.
For the load tests the load generator shared the 4 vCPUs with the server, so absolute
throughput is lower than on separate hosts.

### 1. Prospect list N+1 (`GET /api/prospects/`)

The list now returns, for each prospect, the agent name, property name, tour count,
application count and next scheduled tour. Fetched naively, each of these costs queries
per row. `ProspectQuerySet.with_list_data()` loads them with `select_related` plus
correlated subqueries in the page query.

Seed: 200 prospects, 411 tours, 176 applications, 200 conversations (fixed seed 42).
One 25-row page, in-process via DRF `APIClient`. Each number is the median of 20 requests
after 3 warm-up requests; three separate runs are shown.

| Version | SQL queries / request | Median response time (3 runs) |
|---|---|---|
| Original code (ids only, no related fields) | 3 | 7.78 / 8.45 / 7.63 ms |
| Related fields, **no** `select_related`/subqueries ("before") | 124 | 124.54 / 114.17 / 118.64 ms |
| Related fields, optimized ("after") | **4** | **13.81 / 16.07 / 17.11 ms** |

The "before" row was never in the repo's history. It is the same code with
`with_list_data()` patched to a no-op inside the benchmark process only (see
`perf/bench_prospect_list.py`), which is what the endpoint would cost without the fix.
The query count stays at 4 whatever the page size:
`tests/test_prospect_queries.py` fails if it grows (without the fix it goes 14 → 114).

### 2. Load test on 100,000 prospects

Dataset from `manage.py seed_prospects --count 100000`: 100,000 prospects, 200,126 tours,
80,092 applications, 100,000 conversations, seeded in 149.9 s.
Server: `gunicorn config.wsgi -w 4`, `DJANGO_DEBUG=false`. Client: `perf/loadtest.py`
(httpx, closed loop). **Concurrency 10**, 2,000 requests per endpoint after 50 warm-up
requests, authenticated as the org manager (agent row: as a leasing agent). 0 errors in all runs.

Final code (after both optimizations below):

| Endpoint | p50 | p95 | p99 | req/s |
|---|---|---|---|---|
| `GET /api/prospects/` (page 1) | 65.1 ms | 86.2 ms | 104.0 ms | 149.6 |
| `GET /api/prospects/?page=2..50` | 70.7 ms | 93.2 ms | 112.5 ms | 137.6 |
| `GET /api/prospects/?page=2000` (deep page) | 124.6 ms | 162.4 ms | 184.2 ms | 78.8 |
| `GET /api/prospects/{id}/` | 26.2 ms | 38.2 ms | 47.3 ms | 364.1 |
| `GET /api/prospects/` as leasing agent | 71.2 ms | 90.2 ms | 101.0 ms | 139.7 |
| `GET /api/tours/` | 60.5 ms | 80.7 ms | 94.7 ms | 161.0 |
| `GET /api/applications/` | 37.2 ms | 53.5 ms | 63.2 ms | 257.2 |
| `GET /api/conversations/` | 39.1 ms | 55.1 ms | 67.2 ms | 245.8 |

#### What EXPLAIN ANALYZE showed, and before/after

| Change | SQL time (EXPLAIN ANALYZE) | Endpoint under load, p50 / p99 / req/s |
|---|---|---|
| Deep page `?page=2000`: page ids first, then annotate only those 25 rows | 1,248 ms → 29.3 ms + 1.1 ms | 2,991.4 / 4,007.0 ms / 3.3 → 124.6 / 184.2 ms / 78.8 |
| Applications list: index `(organization, -created_at)` | 48.9 ms → 0.084 ms | 122.3 / 181.6 ms / 79.7 → 36.4 / 61.5 ms / 265.1 |

- **Deep page:** with `OFFSET 49975`, PostgreSQL evaluated the three SELECT-list subqueries
  for every scanned row (`loops=50000`), and the high cost estimate triggered 752 ms of JIT
  compilation. **An index does not help here**: the same OFFSET without annotations is
  already an index scan on `prospect_org_created` (41.9 ms). The fix pages a
  `values_list("pk")` query, then annotates only the ids on the page.
- **Applications:** the plan was a sequential scan plus a top-N heapsort over all 80,092 rows.
  The new index turns it into an index scan with no sort. This is the only index added; no other
  plan showed a missing index.

The "before" rows come from `perf/results/load_1_baseline.json`, which used the same machine,
dataset, server and concurrency.

### Reproduce

```bash
# PostgreSQL 16 running locally with the settings from .env.example
cd backend
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python manage.py migrate

# 1. N+1 benchmark (uses its own throwaway test database)
.venv/bin/python perf/bench_prospect_list.py --prospects 200 --runs 20
.venv/bin/pytest tests/test_prospect_queries.py

# 2. 100K dataset + load test (prints the API tokens used below)
.venv/bin/python manage.py seed_prospects --count 100000
DJANGO_DEBUG=false .venv/bin/gunicorn config.wsgi -w 4 -b 127.0.0.1:8000 &
.venv/bin/python perf/loadtest.py --token <manager token> --agent-token <agent token> \
    --concurrency 10 --requests 2000
```

The "original code" row: check out `cec81e6` in a worktree, copy in `perf/` and
`apps/crm/seeding.py`, and run the benchmark with `--modes current`.

**Limitations:** single machine, synthetic data, one organization holding all 100K
prospects. Tours, applications and conversations are bulk-inserted, so their `created_at`
values sit close together; prospects' `created_at` is spread over about 2 years.
Medians varied by up to ~25% between the three Step 1 runs (13.81 vs 17.11 ms), so treat
small differences as noise.
