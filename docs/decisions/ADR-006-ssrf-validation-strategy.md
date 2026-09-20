# ADR-006: SSRF Validation Strategy for Scraper Targets

## Context

`Target.url` is user-supplied and will eventually be fetched by
Phase 3's workers. Master Prompt Section 3/17 requires SSRF
protection: the platform must not be usable to make the scraping
infrastructure issue requests to internal networks, loopback
addresses, or cloud metadata endpoints on the operator's behalf.

## Decision

A reusable module, `app/core/url_safety.py`, validates:
1. URL scheme is `http` or `https` (nothing else).
2. The resolved IP address(es) for the hostname are not private,
   loopback, link-local (which includes the AWS/GCP/Azure
   `169.254.169.254` metadata endpoint), multicast, reserved, or
   unspecified.

This validation runs **at Target create/update time only** (Decision
#4, Phase 2 scope). It is explicitly **not** sufficient on its own:

**Phase 3 is required to re-validate immediately before every actual
HTTP/browser request, and on every redirect hop, using this same
`url_safety` module** — not to trust that a URL which passed this
check at creation time is still safe when it's actually fetched
(DNS can change between the two moments — DNS rebinding — and this
Phase 2 check has no visibility into redirects, which don't exist
until Phase 3 makes a real request).

## Why not more at Phase 2

- **Real-time DNS re-validation at every scraper run**: not possible
  yet — nothing executes scrapers in Phase 2.
- **Redirect-chain validation**: not possible yet, same reason — no
  HTTP client exists that follows redirects.
- Building either of these now would mean building a scraping
  execution engine to satisfy an SSRF requirement, which Master
  Prompt Section 1.6 and the explicit Phase 2 approval both prohibit
  ("Jangan membangun scheduler, worker, atau execution engine di
  Phase 2 hanya demi menyelesaikan SSRF requirement").

## Design choice: injectable resolver

`url_safety.validate_target_url` accepts an optional `resolver`
argument (defaulting to real OS DNS resolution). This exists purely
so the blocking logic can be unit-tested deterministically without
network access or flaky/slow real DNS lookups — production code
never passes a custom resolver.

## Consequences

- Any Target with a literal dangerous IP (e.g. `169.254.169.254`) is
  rejected immediately, with zero network calls, at both the API
  layer and in tests.
- A hostname-based SSRF attempt (DNS pointing to an internal IP) is
  caught by resolving the hostname at Target creation time — but is
  **not** guaranteed caught if the attacker changes DNS after
  creation and before Phase 3 actually fetches it. This gap is
  intentional, tracked, and Phase 3's re-validation requirement
  (recorded here and in `app/core/url_safety.py`'s own docstring) is
  how it gets closed — not by this ADR alone.
- This is a recorded, explicit dependency Phase 3 must satisfy before
  any engine adapter can be considered complete.
