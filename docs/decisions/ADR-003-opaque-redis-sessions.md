# ADR-003: Opaque Redis Session Tokens over JWT

## Context

Phase 1 needs an authentication token strategy satisfying Section 11:
access tokens, refresh tokens, expiration, logout/revocation, refresh
rotation, and (per explicit Phase 1 approval) protection against
refresh-token reuse and support for multiple concurrent sessions.

## Options considered

1. **JWT (access + refresh)**: self-contained, signed tokens,
   verifiable without a DB/cache round-trip.
2. **Opaque random tokens backed by Redis** (chosen): tokens are
   meaningless random strings; all session state (user, family,
   used/unused, expiry) lives server-side in Redis, keyed by a hash
   of the token.

## Decision

Opaque tokens in Redis. Approved explicitly for Phase 1 with the
instruction not to switch to JWT for "enterprise"/"scalability"
reasons without a concrete justification.

## Reasoning

- **Revocation**: Section 11 requires real logout/revocation. With
  JWT this needs a separate revocation list (defeats the
  "stateless" appeal of JWT in the first place, while adding its own
  storage). With opaque tokens, revocation is `DELETE` on a Redis
  key — trivial and immediate.
- **Refresh rotation + reuse detection** (Phase 1 approval, Decision
  A/H): naturally modeled with Redis — each token pair belongs to a
  `family_id`; rotating marks the old refresh token `used` instead of
  deleting it, so a replay of a used token is detectable and triggers
  revoking the whole family. This requires server-side state either
  way, which JWT alone doesn't provide.
- **No new infrastructure**: Redis is already part of this platform
  (Celery broker, ADR-002) — reusing it for sessions adds zero new
  moving parts. A JWT approach's "no DB/cache needed" advantage
  doesn't materialize here since revocation state has to live
  somewhere anyway (see above).
- **Token-at-rest exposure**: session/refresh token hashes are stored
  as Redis KEYS (SHA-256 of the token), not the plaintext token
  itself — a Redis dump alone does not hand out usable tokens,
  since computing the same hash requires already knowing the
  original token.

## Trade-offs accepted

- Every authenticated request costs one Redis round-trip (vs. JWT's
  in-memory signature check). At this platform's expected scale,
  this is not a meaningful cost, and Redis is already a hard
  dependency of the whole system.
- Horizontal scaling of the API tier requires Redis to be reachable
  from every instance — already true for Celery, no new constraint.

## Why not JWT, explicitly

JWT's main advantages (no server round-trip to verify, no
server-side storage) are exactly the properties Section 11's
revocation/rotation/reuse-detection requirements need to give up
anyway. Choosing JWT here would mean building a Redis-backed
revocation/rotation mechanism ON TOP of JWT — strictly more moving
parts than the opaque-token design, for a "statelessness" benefit
that gets undone by that same mechanism. This is the concrete
justification the Phase 1 approval asked for.

## Consequences

- `apps/api/app/core/sessions.py` — `SessionStore`, keyed by
  `AsyncKeyValueStore` protocol (so it's unit-testable without a real
  Redis — see `apps/api/tests/unit/test_sessions.py`).
- `apps/api/app/core/redis_client.py` — the real Redis client used
  in production/dev, separate from Celery's own Redis connection.
