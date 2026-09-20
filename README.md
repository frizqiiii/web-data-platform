# Web Data Acquisition & Automation Platform

Enterprise-grade web scraping, scheduling, and data pipeline
platform. Built per the Master Engineering Prompt as a Modular
Monolith API + Distributed Workers.

**Status: Phase 0 (Foundation) — no domain features exist yet.**
This repository currently proves the development environment works:
API health checks, a Celery worker running a dummy task, database
migrations, linting/formatting/type-checking, and CI. Nothing here
scrapes anything yet.

## 1. Architecture

See `docs/architecture/overview.md` for the full diagram and
`docs/decisions/` for the ADRs behind each major choice
(modular monolith over microservices, Celery+Redis over Kafka).

## 2. Technology Stack

| Layer | Choice |
|---|---|
| API | FastAPI, SQLAlchemy (async), Alembic, Pydantic |
| Worker | Celery |
| Queue/Broker | Redis |
| Database | PostgreSQL 16 |
| Object storage (local dev) | MinIO |
| Frontend (Phase 9) | Next.js, TypeScript |
| Dependency management | uv (Python), pnpm (Node) |
| Lint/format | ruff |
| Type checking | mypy |
| Testing | pytest, pytest-asyncio |
| CI | GitHub Actions |

## 3. Repository Structure

```
apps/api/         FastAPI application (modular monolith)
apps/worker/      Celery worker (scraping engines land here from Phase 3/5)
apps/scheduler/   Scheduler process (not implemented until Phase 6)
frontend/         Dashboard (not scaffolded until Phase 9)
packages/         Shared contracts/logging/telemetry (empty until needed)
migrations/       Alembic migrations
infrastructure/   Docker, Kubernetes, Helm, Terraform (k8s/helm/terraform empty until Phase 16)
docs/             Architecture, ADRs, operations, security, API docs
tests/            Cross-cutting integration/e2e/performance tests
```

## 4. Local Setup

Prerequisites: Python 3.12, [uv](https://docs.astral.sh/uv/), Docker
and Docker Compose, Node.js + pnpm (only needed once Phase 9 starts).

```bash
git clone <your-fork-url>
cd web-data-platform
cp .env.example .env
uv lock                                   # first time only — generates uv.lock
uv sync --group api --group worker --group scheduler --group dev
```

## 5. Environment Variables

See `.env.example` for the full list with comments. Required at
minimum: `DATABASE_URL`, `REDIS_URL`. Never commit a real `.env`.

## 6. Database & Migrations

```bash
docker compose up -d postgres
uv run alembic -c migrations/alembic.ini upgrade head     # apply
uv run alembic -c migrations/alembic.ini downgrade -1     # roll back one step
uv run alembic -c migrations/alembic.ini revision -m "description"   # new migration
```

## 7. Running the API

```bash
docker compose up -d postgres redis
uv run uvicorn app.main:app --reload --app-dir apps/api
curl localhost:8000/health
curl localhost:8000/ready
```

## 8. Running the Worker

```bash
docker compose up -d redis
uv run celery -A worker.main worker --loglevel=INFO --app-dir apps/worker
```

## 9. Running the Scheduler

Not implemented yet (Phase 6). Running it will raise
`NotImplementedError` on purpose — see
`apps/scheduler/scheduler/main.py`.

## 10. Running the Frontend

Not scaffolded yet (Phase 9). See `frontend/dashboard/README.md`.

## 11. Running Tests

```bash
# Unit tests only (no live Postgres/Redis needed):
uv run pytest -m "not integration"

# Full suite, including integration tests (requires docker-compose up):
docker compose up -d postgres redis
uv run pytest --cov --cov-report=term-missing
```

## 12. Docker

```bash
docker compose up -d --build
docker compose ps        # all services should report healthy
```

`scheduler` is excluded from the default `up` (opt-in via
`docker compose --profile scheduler up scheduler`) because it isn't
implemented yet and will intentionally exit non-zero.

## 13. API Documentation

Once the API is running: `http://localhost:8000/docs` (Swagger UI,
auto-generated from FastAPI). Currently only documents `/health` and
`/ready`.

## 14. Security Considerations (Phase 0)

No authentication/authorization exists yet — this repository has no
protected endpoints. Secrets are never committed (`.env` is
gitignored, only `.env.example` with placeholder values is tracked).
Full security posture builds out starting Phase 1 (`docs/security/`).

## 15. Deployment Overview

Not implemented. Kubernetes/Helm/Terraform directories exist as
empty placeholders reserved for Phase 16 — populating them now with
no application to deploy would be premature.

## 16. Known Limitations (updated through Phase 2)

- Scheduler is a stub that intentionally fails (Phase 6 territory).
- Frontend is not scaffolded (Phase 9).
- No scraper engine adapters exist — `Scraper.engine`/`configuration`
  are domain fields only; nothing executes a scraper yet (Phase 3).
- No job/queue/scheduling system — `Project`/`Scraper`/`Target` are
  definitions only, not executable work (Phase 4/5/6). See
  `docs/architecture/execution-command-contract.md` for the forward-
  looking design.
- `Scraper.credential_reference` is a plain string identifier, NOT a
  secret store — nothing resolves it to an actual credential, and no
  encrypted storage exists. A scraper with this field set is not a
  fully executable authenticated scraper (Decision #2, Phase 2 plan).
- API responses do not use a generic `{"data", "meta"}` envelope —
  see `docs/decisions/ADR-007-response-format-deviation.md` for why
  this deviates from the Master Prompt.
- See `PHASE_0_REPORT.md`, `PHASE_1_REPORT.md`, `PHASE_2_REPORT.md`
  for the full, current list of what is and isn't verified.
