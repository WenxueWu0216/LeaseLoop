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
