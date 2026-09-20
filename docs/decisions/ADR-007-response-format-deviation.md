# ADR-007: Deviation from Master Prompt's Generic Response Envelope

## Context

Master Prompt Section 9 specifies a generic response envelope for
every endpoint: `{"data": {...}, "meta": {...}}` for success and
`{"error": {"code", "message", "request_id"}}` for failures. Phase 1
(already PASS, not reopened) implemented every endpoint returning its
Pydantic response schema directly, with FastAPI's default
`{"detail": ...}` error shape — not this envelope.

## Decision

The project will **not** adopt the generic envelope as a global
requirement, for Phase 2 or going forward, absent a new concrete
need. Endpoints return clear, well-typed response schemas directly
(Option C from the Phase 2 planning decision).

## Reasoning

- Phase 1's endpoints already ship this way and are PASS — retrofitting
  them purely for consistency is a breaking change with no functional
  benefit, and was explicitly ruled out ("Jangan membuka kembali atau
  memodifikasi endpoint Phase 1 hanya untuk mengubah format response").
- No current consumer (there is no frontend yet — Phase 9) requires
  the generic envelope shape.
- A wrapper object with no consumer that needs it is exactly the kind
  of boilerplate Section 1.6 warns against.

## What this does NOT mean

- Pagination metadata is still used where genuinely needed (e.g. a
  future paginated list endpoint can return
  `{"data": [...], "meta": {"page", "page_size", "total"}}` — the
  envelope is available as a *pattern*, just not mandatory everywhere).
- Error handling still needs to stay consistent (see Section 60's
  error taxonomy) — this ADR only concerns the outer JSON shape, not
  whether errors are informative or correctly status-coded.
- If a future phase (a real frontend/BFF in Phase 9, or an API
  gateway in Phase 18) needs the envelope, that need must be
  addressed via a **new ADR with explicit approval** — this decision
  is not permanent, just not adopted speculatively now.

## Consequences

Every Phase 2 endpoint (`ProjectResponse`, `ScraperResponse`,
`TargetResponse`, and their list forms) follows the same pattern as
Phase 1's `UserResponse`/`OrganizationResponse`: the schema directly,
no wrapper.
