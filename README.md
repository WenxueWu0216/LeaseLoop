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

## Performance (measured, 100K prospects)

| | Before | After |
|---|---:|---:|
| Queries per prospect-list page | 72 | 5 |
| Prospect list p50, sequential | 82.7 ms | 15.7 ms |
| All endpoints p95, Locust 100 users (~75 req/s) | 176 ms | 55 ms |

Setup, query plans, full tables and how to reproduce: [docs/perf.md](docs/perf.md).
