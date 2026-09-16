# Architecture Overview

This is the baseline architecture from the Master Engineering Prompt
(Section 4), unchanged in Phase 0.

```
                     ┌──────────────────────┐
                     │      Next.js         │
                     │      Dashboard       │   (skeleton only — Phase 9)
                     └──────────┬───────────┘
                                │
                                ▼
                     ┌──────────────────────┐
                     │       FastAPI        │
                     │   Modular Monolith   │   ← implemented in Phase 0 (health/ready only)
                     └──────────┬───────────┘
                                │
             ┌──────────────────┼──────────────────┐
             │                  │                  │
             ▼                  ▼                  ▼
        PostgreSQL           Redis            Object Storage (MinIO)
             │                  │
             │                  ▼
             │              Task Queue (Celery)
             │                  │
             │        ┌─────────┼─────────┐
             │        ▼         ▼         ▼
             │     Worker 1  Worker 2  Worker N   ← skeleton (ping task only) — Phase 0
             │        │         │         │
             │        └─────────┼─────────┘
             │                  ▼
             │          Scraping Engine            (Phase 3)
             │                  │
             │                  ▼
             │           Data Processing            (Phase 7)
             │                  │
             └──────────────────┘
                     Scheduler                       (raises NotImplementedError — Phase 6)
                         │
                         ▼
                       Queue
```

## Rules that constrain this architecture (see ADRs)

- Modular Monolith API + Distributed Workers is the default and is
  not to be silently converted to microservices (ADR-001).
- Celery + Redis is the queue baseline; task interfaces are written
  so a future broker swap doesn't require rewriting business logic
  (ADR-002).
- The dashboard never talks to Postgres/Redis/the scraping engine
  directly — only to the API.

## What exists after Phase 0

Only: FastAPI app with `/health` and `/ready`, a Celery worker that
can run a dummy `ping` task, a scheduler process that intentionally
fails fast (not implemented), Alembic wired to a real Postgres with
one baseline migration, and the Docker Compose topology for local
dev. No domain logic (users, organizations, projects, scrapers,
jobs, ...) exists yet — that begins Phase 1.
