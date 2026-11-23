# ADR-008: Engine Abstraction & Deferred Browser/Scrapy Implementation

## Context

Phase 2 established three `ScraperEngine` values — `HTTP`, `BROWSER`,
`SCRAPY` — with engine-specific configuration schemas already
in place (`app/schemas/scraper_configuration.py`). Phase 3 needs to
actually execute a scraper against a target, for at least one of
these engines, from the worker (`apps/worker`), without coupling the
execution layer to FastAPI, SQLAlchemy, or any API-layer object.

Two questions had to be settled before writing any engine code:

1. What is the shape every engine must implement, so the worker can
   dispatch to any of them uniformly?
2. Which engine(s) get a real implementation in Phase 3, and what do
   the other(s) do instead?

## Decision

### Engine interface: `Protocol`, not `ABC`

```python
class EngineAdapter(Protocol):
    async def execute(self, context: ExecutionContext) -> ExecutionResult: ...
```

A `typing.Protocol`, not an abstract base class. Nothing elsewhere in
this codebase established an ABC convention for pluggable
implementations that Phase 3 needed to follow, so the smaller
commitment (structural typing — any object with a matching `execute`
method satisfies the interface, no inheritance required) was taken.

`EngineAdapter.execute` receives a single `ExecutionContext` (an
immutable, plain-value snapshot — see the "Execution model" section
of the Phase 3 spec and `worker/core/execution.py`) and returns a
single `ExecutionResult`. It receives no FastAPI request object, no
`AsyncSession`, no ORM model, and performs no authorization check —
whatever assembles an `ExecutionContext` from real `Scraper`/`Target`
rows (a future phase's dispatch/queue code) is responsible for all of
that; the engine's entire world is the context it's handed.

### HTTP: real implementation. Browser/Scrapy: interface + stub only

Only the HTTP engine (`worker/engines/http/engine.py`) does real work
in Phase 3 — genuine `httpx`-based requests, subject to the full
SSRF/IP-pinning/redirect/size/timeout pipeline (ADR-009 covers the
IP-pinning half of this in detail).

`BrowserEngineAdapter` and `ScrapyEngineAdapter` are interface-only
stubs. Neither Playwright nor Scrapy is installed. Calling either
adapter's `execute` always returns a classified, non-retryable
`ExecutionResult` with `ErrorCategory.ENGINE_UNSUPPORTED` — never a
crash, never a silent no-op, never a result that could be mistaken
for a real (if degenerate) execution.

## Reasoning

- **Installing a dependency "to make the checklist look complete" is
  worse than not installing it.** A Playwright or Scrapy integration
  written against an unverified runtime environment (no confirmed
  browser binary availability, no confirmed resource limits
  appropriate for headless Chromium, no confirmed way to test it in
  this sandbox at all — see PHASE_3_REPORT.md's environment
  constraints) would be exactly the kind of code this project's own
  stated engineering standard rejects: security and architectural
  correctness matter more than a checklist appearing done.
- **A classified `ENGINE_UNSUPPORTED` result is strictly better than
  either a crash or a fake success.** Whatever calls `EngineResolver`
  in a later phase gets a real, typed answer it can act on (e.g. "this
  scraper's target engine isn't available yet, don't schedule it") —
  not an exception it has to special-case, and not a result that
  looks like a legitimate 0-byte fetch.
- **The future security design is recorded now, not deferred blindly.**
  Both stub modules' docstrings document what a real implementation
  must do — a Playwright `page.route("**/*")` interceptor validating
  every sub-request through the same `resolve_and_pin` the HTTP engine
  uses; a Scrapy Downloader Middleware doing the same — so the future
  increment that actually builds these doesn't have to re-derive the
  security requirements from scratch, and so nobody can build a
  "working" browser/Scrapy engine later that quietly skips SSRF
  validation because nobody wrote down that it needed one.

## What this does NOT mean

- This is not a statement that Browser/Scrapy engines are low
  priority — only that a real implementation needs a verified runtime
  environment first, which Phase 3 did not have.
- `EngineResolver` (see `worker/engines/resolver.py`) is written so
  that swapping a stub adapter for a real one later is a one-line
  change — the resolver dispatches by engine-name string to whatever
  `EngineAdapter` is registered, and callers never need to know
  whether they're holding a stub or a real adapter.
