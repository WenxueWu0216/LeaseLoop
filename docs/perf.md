# Performance: N+1 fix, query plans and load test

Every number on this page was measured on the setup below. Where a number varies between
runs, the page says so. The raw `EXPLAIN ANALYZE` output is in
[`perf/explain_after.txt`](perf/explain_after.txt) (sections 1–4) and
[`perf/explain_2026-11_before.txt`](perf/explain_2026-11_before.txt) /
[`perf/explain_2026-11_after.txt`](perf/explain_2026-11_after.txt) (section 5).

> **Current numbers are in section 5.** Sections 1–4 were measured before the inbox gained
> its last-message and handoff columns. That change slowed the inbox down, and the 100-user
> p95 for `main` as merged was 99 ms, not 55 ms. Section 5 shows the regression, its fix, and
> a fresh load test.

## Summary

| What | Before | After |
|---|---:|---:|
| Queries per prospect-list page (25 rows) | 72 | 5 |
| Prospect list page load, sequential p50 | 82.7 ms | 15.7 ms (**5.3x**) |
| Prospect list p50 under load (100 users) | 94 ms | 22 ms (**4.3x**) |
| All endpoints p95 under load (100 users, ~75 req/s) | 176 ms | 55 ms |
| All endpoints p99 under load (100 users) | 226 ms | 83 ms |
| COUNT for `?status=CONTACTED` (EXPLAIN ANALYZE) | 13.2 ms | 1.0 ms |

"Before" is commit `d399021` (Stage 2, the list endpoint written the straightforward way).
"After" is `aaeb6b6`. Both fixes are described below. The p95 target was 150 ms. Before the
fixes, the 100-user run was over it (176 ms). After, it was well under it (55 ms).

**Current code (section 5), same 100-user test:**

| What | `main` as merged (`de518ed`) | Now |
|---|---:|---:|
| All endpoints p95 / p99 | 99 ms / 145 ms | **50 ms / 76 ms** |
| Inbox (`/api/conversations/`) p95 | 156 ms | 49 ms |
| Deep prospect pages p95 | 65 ms | 38 ms |
| Last prospect page, sequential p50 | 49.9 ms | 18.0 ms |

## Setup

| | |
|---|---|
| Machine | 4 vCPU Intel Xeon @ 2.80 GHz, 15 GB RAM (cloud container) |
| Database | PostgreSQL 16.15, default config (`shared_buffers` 128 MB, `work_mem` 4 MB), same host |
| App server | gunicorn, 4 sync workers, `DJANGO_DEBUG=false`, Django 5.1.4, DRF 3.15.2 |
| Load generator | Locust 2.32.5, **same host** (competes with the app and DB for the 4 CPUs) |
| Data | `seed_demo --prospects 100000`: 4 orgs, 20 properties, 2,400 units, 100,000 prospects, 100,000 conversations, 250,422 messages, 40,001 tours, 15,074 applications, 6,059 leases. `crm_prospect` is 46 MB with indexes |

Each org holds 25,000 prospects, so a tenant-scoped list query works over 25K rows.

## 1. Finding the N+1

Every request goes through `RequestMetricsMiddleware`
([`apps/core/middleware.py`](../backend/apps/core/middleware.py)). It counts queries and DB
time with `connection.execute_wrapper`, so it works with `DEBUG=False`. The results go into
the JSON request log and the `X-DB-Query-Count` and `Server-Timing` response headers.
Requests over 30 queries or 500 ms log at WARNING.

[`scripts/perf/probe.py`](../scripts/perf/probe.py) makes 30 sequential requests per endpoint
over HTTP after 3 warm-up requests, and reads those headers.

**Before (`d399021`):**

| Endpoint | Queries | p50 ms | p95 ms | DB ms (p50) |
|---|---:|---:|---:|---:|
| Prospect list (manager, page 1) | 72 | 82.7 | 134.3 | 32.2 |
| Prospect list, status=CONTACTED | 72 | 93.1 | 118.7 | 43.9 |
| Prospect list (agent scope) | 60 | 75.8 | 110.9 | 30.5 |
| Prospect list, page 500 | 70 | 89.1 | 124.7 | 46.2 |
| Prospect search q=smith | 73 | 117.0 | 151.1 | 61.2 |
| Prospect detail | 10 | 15.4 | 24.5 | 4.0 |
| Tours, upcoming | 4 | 17.0 | 24.3 | 8.4 |
| Units, available | 4 | 9.0 | 16.7 | 2.0 |
| Conversations (inbox) | 4 | 9.2 | 11.6 | 2.8 |

The list query count tracked the number of rows. That pointed at the serializer.
`ProspectListSerializer` nests the assigned agent and interested property, and computes
`next_tour` with `prospect.tours.filter(...).first()` and then `tour.unit.number`. Each row
therefore cost up to four extra queries: agent, property, next tour, and that tour's unit.
Rows with no agent or property skip some of them, so the count varies a little by page.

**Fix (`14df4d2`):** in `ProspectViewSet.get_queryset`:

```python
qs.select_related("assigned_agent", "interested_property").prefetch_related(
    Prefetch("tours", queryset=upcoming_tours.select_related("unit"), to_attr="upcoming_tours")
)
```

The serializer reads `prospect.upcoming_tours` when it has been prefetched. A page now costs
5 queries whatever its size: token auth, membership, COUNT, the page with both foreign keys
joined, and one `IN (...)` query for upcoming tours with their units.

`select_related` is right for the two foreign keys, because each is a single joined row.
`prefetch_related` is right for tours, because joining a reverse foreign key would multiply
the page rows and break `LIMIT 25`.

**Regression guard:** [`tests/test_query_counts.py`](../backend/tests/test_query_counts.py)
asserts the list query count is the same for 1 and 25 rows, and pins the detail view. On the
pre-fix code, the same tests fail with *"Expected to perform 4 queries but 103 were done"*
for 25 rows, and *"…6 queries but 10 were done"* for detail.

## 2. Unneeded `SELECT DISTINCT` on filtered lists

After the N+1 fix, `?status=` was still slower than the unfiltered list (p50 31.5 ms vs
19.0 ms). Running `EXPLAIN ANALYZE` on the endpoint's actual SQL (`manage.py perf_explain`)
showed why. Both the page query and the paginator's COUNT were wrapped in
`SELECT DISTINCT` over every selected column. The COUNT became
`SELECT COUNT(*) FROM (SELECT DISTINCT …)` and took **13.2 ms**. The planner also used the
org-only index and discarded 18,878 of 25,000 rows by filter.

The cause is django-filter's `MultipleChoiceFilter`, which defaults to `distinct=True`. None
of these filters join to-many relations, so duplicates are impossible and the `DISTINCT` was
pure overhead.

**Fix (`aaeb6b6`):** `distinct=False`. The COUNT is now an **Index Only Scan** on
`prospect_org_status_created (organization, status, -created_at)` in **1.0 ms**, and the
filtered list's sequential p50 went from 31.5 ms to 14.0 ms.

## 3. Index check (after both fixes)

These come from `EXPLAIN ANALYZE` on the real endpoint SQL against org 1 (25K prospects).
Each request runs a COUNT query and a page query.

| Request | COUNT plan | COUNT | Page plan | Page |
|---|---|---:|---|---:|
| `/api/prospects/` | Index Only Scan, org index | 2.5 ms | Index Scan `prospect_org_created` + incremental sort on `id` | 0.24 ms |
| `?status=CONTACTED` | Index Only Scan `prospect_org_status_created` | 1.0 ms | Index Scan `prospect_org_status_created` | 0.19 ms |
| `?q=smith` | Index Scan on org, filter `UPPER(col) LIKE '%SMITH%'` on 4 columns | 27.4 ms | Index Scan `prospect_org_created` + filter | 2.3 ms |
| `?page=500` | Index Only Scan, org index | 2.5 ms | Index Scan `prospect_org_created`, reads 12,500 rows for OFFSET | 28.5 ms |

The tenant-first composite indexes were part of the Stage 1 schema. These plans confirm they
are used for the main list and status filter. Two costs remain, and both are understood:

- **Search** uses `icontains` on four columns, which no B-tree index can serve. Every
  matching org row is scanned and filtered.
- **Deep OFFSET pages** read and discard `offset` rows.

Both stay within the latency target under load (next section). The options for them are
listed at the end.

## 4. Load test

[`scripts/perf/locustfile.py`](../scripts/perf/locustfile.py) simulates managers (25%) and
agents (75%) spread across the 4 orgs. Each user waits 0.5 to 2 seconds between requests.
The task weights are:

| Task | Weight |
|---|---:|
| List page 1 | 10 |
| Detail | 8 |
| Status filter | 5 |
| Inbox | 4 |
| Search | 3 |
| Upcoming tours | 3 |
| Random page 2–200 | 2 |
| Available units | 2 |

Each run lasts 3 minutes with a spawn rate of 25 users/s.

Percentiles come from every recorded request, after dropping the first 15 seconds of warm-up
and the setup requests ([`scripts/perf/summarize.py`](../scripts/perf/summarize.py)).

**After the fixes (`aaeb6b6`), 50 users:**

| Endpoint | Requests | Errors | p50 ms | p95 ms | p99 ms | req/s |
|---|---:|---:|---:|---:|---:|---:|
| `/api/conversations/` | 699 | 0 | 28 | 42 | 49 | 4.3 |
| `/api/prospects/` | 1728 | 0 | 21 | 30 | 36 | 10.5 |
| `/api/prospects/?page=N` | 340 | 0 | 33 | 52 | 62 | 2.1 |
| `/api/prospects/?q=` | 527 | 0 | 51 | 84 | 112 | 3.2 |
| `/api/prospects/?status=` | 909 | 0 | 19 | 26 | 34 | 5.5 |
| `/api/prospects/{id}/` | 1350 | 0 | 17 | 25 | 33 | 8.2 |
| `/api/tours/` | 559 | 0 | 17 | 24 | 30 | 3.4 |
| `/api/units/` | 346 | 0 | 12 | 17 | 22 | 2.1 |
| **All endpoints** | 6458 | 0 | 20 | 50 | 78 | 39.4 |

**After the fixes (`aaeb6b6`), 100 users:**

| Endpoint | Requests | Errors | p50 ms | p95 ms | p99 ms | req/s |
|---|---:|---:|---:|---:|---:|---:|
| `/api/conversations/` | 1370 | 0 | 28 | 45 | 57 | 8.4 |
| `/api/prospects/` | 3475 | 0 | 22 | 37 | 55 | 21.3 |
| `/api/prospects/?page=N` | 672 | 0 | 34 | 57 | 71 | 4.1 |
| `/api/prospects/?q=` | 995 | 0 | 55 | 93 | 112 | 6.1 |
| `/api/prospects/?status=` | 1741 | 0 | 20 | 34 | 56 | 10.7 |
| `/api/prospects/{id}/` | 2789 | 0 | 18 | 32 | 49 | 17.1 |
| `/api/tours/` | 1034 | 0 | 18 | 30 | 45 | 6.3 |
| `/api/units/` | 716 | 0 | 13 | 24 | 39 | 4.4 |
| **All endpoints** | 12792 | 0 | 21 | 55 | 83 | 78.5 |

**Before the fixes (`d399021`), 100 users, same data and same script:**

| Endpoint | Requests | Errors | p50 ms | p95 ms | p99 ms | req/s |
|---|---:|---:|---:|---:|---:|---:|
| `/api/conversations/` | 1353 | 0 | 50 | 142 | 188 | 8.3 |
| `/api/prospects/` | 3386 | 0 | 94 | 187 | 232 | 20.7 |
| `/api/prospects/?page=N` | 641 | 0 | 104 | 199 | 244 | 3.9 |
| `/api/prospects/?q=` | 965 | 0 | 125 | 206 | 262 | 5.9 |
| `/api/prospects/?status=` | 1621 | 0 | 98 | 187 | 239 | 9.9 |
| `/api/prospects/{id}/` | 2604 | 0 | 42 | 133 | 189 | 16.0 |
| `/api/tours/` | 1045 | 0 | 41 | 136 | 179 | 6.4 |
| `/api/units/` | 656 | 0 | 39 | 124 | 176 | 4.0 |
| **All endpoints** | 12271 | 0 | 80 | 176 | 226 | 75.2 |

Before the fix, endpoints with no N+1 of their own were also slow (`/api/units/` p95 124 ms
vs 24 ms after). All endpoints share 4 sync workers, so slow list requests made every other
request wait in the queue.

### Notes and caveats

- **Login is excluded on purpose.** In a first run where each simulated user logged in during
  ramp-up, 50 concurrent PBKDF2 password hashes took up all 4 workers. That pushed the
  aggregate p99 to 2.6 s even though steady-state endpoints were fine. The final runs reuse
  the API tokens created by `seed_demo` (`manage.py demo_tokens`). Login cost is real, but
  it happens once per session, not on every page.
- **Same-host load generator.** Locust, gunicorn and Postgres share 4 vCPUs, so these numbers
  are pessimistic compared with separate machines. They are also not production numbers:
  there is no network hop, and the database is local with default config.
- **Run-to-run variance.** Separate sequential probes of the same post-N+1-fix list endpoint
  gave p50 of 19.0 ms and 15.7 ms. Treat differences of a few milliseconds as noise.

### Not done yet, and when it would be worth it

- **Search:** a `pg_trgm` GIN index over the searched columns would turn the 27 ms filtered
  scan into an index lookup. Search is the slowest endpoint (p95 93 ms at 100 users), so it
  is the first thing to change if load or data grows.
- **Deep pages:** addressed in section 5 by paging over ids first and adding an index that
  matches the sort. Keyset/cursor pagination would also remove the COUNT, at the cost of
  "jump to page N".

## 5. Follow-up (November 2026): deep pages, list index, and an inbox regression

All measurements here were taken on the same 100K-prospect seed, the same machine and the same
scripts as above. The demo data was regenerated after sections 1–4 (same size and generator,
with timestamps no longer allowed in the future), so compare numbers within this section.

**Deep prospect pages.** `EXPLAIN ANALYZE` of the last page (`?page=1000`) showed that, at large
offsets, Postgres stopped using the `(organization, -created_at)` index. It ran a parallel
sequential scan of the org's 25,000 rows, did a full sort on `(created_at, id)` (the index had
no `id` tie-breaker), and joined agent and property for **all 25,000 rows** to return 25:
43.5 ms.

Two changes, measured one at a time:

| Last page, `?page=1000` | DB time per request (p50) | Request p50 / p95 |
|---|---:|---:|
| `main` as merged | 38.7 ms | 49.9 / 73.3 ms |
| A. Page over ids first, then load and join only that page's rows | 13.1 ms | 27.3 / 31.0 ms |
| A + B. Replace the index with `(organization, -created_at, -id)` | **7.0 ms** | **18.0 / 22.0 ms** |

- **A.** The id query touches `crm_prospect` alone; the joins and the tours prefetch run for
  25 rows (page query 43.5 ms → 0.3 ms). This adds one query per request (5 → 6 over HTTP, 4
  → 5 in tests), and page 1 did not get slower (p50 16.7 → 17.7 ms, within run-to-run noise).
- **B.** With the id tie-breaker in the index, the id query became an Index Only Scan with no
  sort step: 11.9 ms → 3.3 ms on the last page. The new index replaces the old one rather than
  adding a second, so writes don't maintain an extra index.

This idea came from an earlier experiment branch (`perf-benchmarks`, closed). It was
re-implemented and re-measured here, so the numbers above belong to this code.

**Inbox regression.** The probe showed the inbox at p50 87.1 ms with 75 ms of DB time. In
sections 1–4 it was about 10 ms. The cause was the Stage 4 inbox annotation
`Count("handoffs")`. Being an aggregate over a join, it made Postgres `GROUP BY` all 25,008 of
the org's conversations, joined to prospects, *before* `ORDER BY ... LIMIT` picked the page.
The paginator's COUNT inherited the same `GROUP BY`. The fix computes the open-handoff count as
a correlated subquery, like the last-message columns, so nothing is grouped and the page comes
straight off the `(organization, -last_message_at)` index:

| Inbox | Page query | COUNT | Request p50 (sequential) |
|---|---:|---:|---:|
| `main` as merged | 90.8 ms | 17.3 ms | 87.1 ms |
| Correlated subquery | **0.65 ms** | **2.1 ms** | **12.8 ms** |

A test pins the zero-handoff case (`Coalesce` to 0). The inbox query-count test passed both
before and after, because the problem was the cost of each query, not how many queries ran.

**Load test, current code** (same Locust script and task mix as section 4, 100 users, 3 minutes):

| Endpoint | `main` as merged p50 / p95 / p99 | Now p50 / p95 / p99 |
|---|---:|---:|
| `/api/conversations/` | 86 / 156 / 193 | 31 / 49 / 64 |
| `/api/prospects/` | 22 / 58 / 96 | 23 / 38 / 56 |
| `/api/prospects/?page=N` | 30 / 65 / 110 | 26 / 38 / 57 |
| `/api/prospects/?q=` | 44 / 90 / 136 | 47 / 83 / 103 |
| `/api/prospects/?status=` | 20 / 54 / 90 | 22 / 34 / 46 |
| `/api/prospects/{id}/` | 21 / 53 / 88 | 21 / 34 / 49 |
| `/api/tours/` | 23 / 59 / 99 | 23 / 38 / 50 |
| `/api/units/` | 15 / 46 / 76 | 15 / 26 / 43 |
| **All endpoints** | **24 / 99 / 145** (77.7 req/s) | **23 / 50 / 76** (78.4 req/s) |

Both runs had 0 errors. At 50 users the current code measured p50 / p95 / p99 of
22 / 41 / 66 ms at 39.7 req/s. In the merged run, the slow inbox also raised p95 on endpoints
that didn't change, because all endpoints share the same 4 gunicorn workers.

Search (`?q=`) is still the slowest endpoint. The `pg_trgm` option under "Not done yet" still
applies.

## Reproduce

```bash
cd backend
python manage.py seed_demo --prospects 100000 --reset
DJANGO_DEBUG=false gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 4
```
```bash
python scripts/perf/probe.py --runs 30
```
```bash
python manage.py perf_explain --query "status=CONTACTED"      # or --endpoint conversations
```
```bash
python manage.py demo_tokens > /tmp/tokens.json
```
```bash
LOCUST_TOKENS=/tmp/tokens.json LOCUST_RAW_CSV=/tmp/raw.csv locust -f scripts/perf/locustfile.py \
  --host http://127.0.0.1:8000 --headless -u 100 -r 25 -t 3m
```
```bash
python scripts/perf/summarize.py /tmp/raw.csv
```

To measure the "before" state, check out `d399021` and repeat the same steps.
