# ADR-001: Modular Monolith over Microservices

## Context

The Master Engineering Prompt (Section 4) specifies a baseline
architecture of "Modular Monolith API + Distributed Workers". This
project starts from zero, with unknown initial team size (likely
solo or very small).

## Decision

Build the API as a single FastAPI application organized into
modules (`apps/api/app/modules/{auth,users,organizations,...}`)
rather than as separate deployable services per domain. Workers and
the scheduler are separate deployment units (they scale differently
from the API and from each other), but the API domain logic itself
stays in one process/repo.

## Alternatives considered

- **Full microservices per domain** (separate service for auth,
  projects, scrapers, jobs, ...): rejected for now. Section 1.6
  explicitly warns against unnecessary complexity, and microservices
  add real operational cost (service discovery, distributed
  transactions, inter-service auth, more CI/CD surfaces) that isn't
  justified by current scale or team size.
- **Single process for everything, including workers**: rejected —
  scraping/processing workloads have fundamentally different scaling
  and failure characteristics than the API (Section 54: workers must
  be horizontally scalable independent of the API), so they are
  separate deployment units from day one even though the domain code
  is one repo.

## Trade-offs

- Pro: simpler deployment, simpler local dev, simpler transactions,
  faster iteration for a small team.
- Con: the whole API scales as one unit; a hot module can't be
  scaled independently of a cold one. Acceptable at current scale;
  revisit if/when a specific module's load characteristics diverge
  enough to justify the operational cost of splitting it out.

## Consequences

- `apps/api/app/modules/` is the extension point for new domain
  functionality (Phase 1 onward), not new repos or new services.
- If this decision needs to change later, Section 1.4's process
  applies: document why, alternatives, trade-offs, migration impact,
  and get explicit approval before doing it — it will not happen
  silently.
