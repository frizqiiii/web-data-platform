# ADR-002: Celery + Redis as the Initial Queue

## Context

The platform needs asynchronous, distributed job execution for
scraping and data processing (Master Engineering Prompt Section 26).
Section 1.6 warns against introducing infrastructure (e.g. Kafka)
without a justified requirement.

## Decision

Use Celery as the task execution framework with Redis as both broker
and result backend for Phase 0 through at least Phase 5. Task
interfaces (queue names, task signatures) are kept broker-agnostic
in how they're called from application code, so swapping the broker
later (e.g. to RabbitMQ) would mean changing Celery configuration,
not rewriting call sites.

## Alternatives considered

- **Kafka**: rejected for now — Kafka is a log/streaming platform,
  not a task queue; using it as one adds significant operational
  complexity (partitions, consumer groups, offset management) with
  no corresponding requirement here. Reconsider only if the platform
  later needs genuine event streaming/replay semantics.
- **RabbitMQ as broker**: viable alternative, but Redis is already
  required elsewhere (rate limiting, caching potential) so reusing
  it as the broker avoids running a second piece of infrastructure
  in Phase 0. This is revisited if Redis becomes a bottleneck for
  either use case.
- **Custom polling-based job queue on Postgres**: rejected — reinvents
  retry/backoff/DLQ semantics that Celery already provides correctly.

## Trade-offs

- Pro: mature ecosystem, built-in retry/backoff/rate-limiting
  primitives, one fewer infrastructure component to run locally.
- Con: Redis-as-broker has weaker delivery guarantees than a
  dedicated message broker (e.g. no built-in dead-lettering as
  robust as RabbitMQ's) — Section 29's DLQ requirements will need to
  be implemented at the application level (Phase 5), not assumed
  from the broker.

## Consequences

- `apps/worker/worker/main.py` configures Celery with Redis from
  `WorkerSettings.redis_url`.
- Logical queue names from Section 26 (`scrape.high`, `scrape.default`,
  ...) are reserved as a naming convention now but not yet routed to,
  since no real tasks exist to route in Phase 0.
