# Phase 3 Report — Scraping Engine & Execution Foundation

> **Status update:** Section 19 reflects real execution results and supersedes the UNVERIFIED tags in the other sections, which were written before dependencies could be installed. Only Docker image builds remain UNVERIFIED.

## 1. Executive Summary

Phase 3 built the execution foundation described in the handoff:
`ExecutionContext` → `EngineResolver` → `EngineAdapter` →
`ExecutionResult`/`ExecutionError`, a real HTTP engine with
SSRF-revalidation and DNS-rebinding-safe IP-pinning, Browser/Scrapy
interface stubs, a `CredentialProvider` abstraction with fail-closed
behavior, worker structured logging, two ADRs, a capability matrix,
and an updated execution-command-contract document.

**Environment constraint, stated up front and applying to every
"UNVERIFIED" tag below:** this sandbox has no network access and no
third-party Python packages installed (`httpx`, `structlog`,
`celery`, `fastapi`, `pytest`, `mypy`, `ruff` are all absent —
confirmed by attempting `pip install httpx`, which fails with "No
matching distribution found"). This is the same constraint every
prior phase's report already documents. Where evidence could be
gathered without those dependencies (pure-stdlib logic), it was
gathered by actually executing the code via a manual test harness —
not by inspection alone — and is reported as such. Where it could
not, the item is marked `UNVERIFIED`, never `PASS`.

**No new ZIP was received for this continuation** — the file at
`/mnt/user-data/uploads/web-data-platform-main.zip` is byte-identical
(same MD5) to the one audited in the previous response. Work
proceeded against that same, already-audited repository state, since
its content matches what the continuation prompt described.

## 2. Initial Repository Audit

Not repeated — see the prior response's "PHASE 3 INITIAL AUDIT",
which remains accurate (same ZIP). Summary: Phase 2 (Project /
Scraper / Target, SSRF creation-time validation) is complete and
untouched by this work. The worker was a Phase-0 stub (`ping` task
only) with empty, pre-scaffolded `engines/{http,browser,scrapy}/`,
`parsers/`, `processors/`, `storage/` directories — Phase 3 filled in
`engines/` only, per scope.

## 3. Repository vs. Previous Handoff Differences

One difference not fully anticipated by either handoff, discovered
during implementation:

- **`Dockerfile.api`/`Dockerfile.worker` only `COPY` their own app
  directory and scope `PYTHONPATH` to it.** Decision #1 (shared
  `packages/security/url_safety.py`) would have worked in pytest
  (once `pythonpath` includes the repo root) but silently failed at
  actual container runtime — the shared module would never ship in
  either image. This was reported and resolved per the "conflict
  resolution" instructions: both Dockerfiles now also `COPY packages
  ./packages` and extend `PYTHONPATH` to include `/app`, keeping the
  existing `/app/apps/{api,worker}` entry first so nothing about
  existing `app.*`/`worker.*` imports changes.

No other conflicts between the handoff and the actual repository were
found.

## 4. Decisions Applied

### Decision #1 — Shared SSRF module: DONE

`packages/security/url_safety.py` is the single implementation
(`validate_target_url`, `is_safe_ip`, `SystemResolver`,
`HostnameResolver`, plus new `resolve_and_pin`/`PinnedTarget`).
`apps/api/app/core/url_safety.py` is now a compatibility re-export
shim — verified by import-identity check (`app.core.url_safety.
validate_target_url is packages.security.url_safety.validate_target_url`
→ `True`) and by re-running the existing test file's exact fixtures
manually (see Section 16). `apps/worker` imports the shared module
directly (no shim needed, no prior worker code to stay compatible
with).

### Decision #2 — Browser/Scrapy interface-only: DONE

Real HTTP engine; `BrowserEngineAdapter`/`ScrapyEngineAdapter` are
interface-only stubs always returning `ENGINE_UNSUPPORTED`,
`retryable=False`. No Playwright, no Scrapy installed. Future
security design documented in each stub's docstring and in ADR-008.

### Decision #3 — Full IP-pinning: DONE

`resolve_and_pin` resolves once, validates every candidate, returns a
`PinnedTarget`. The HTTP engine connects to `pinned_ip` directly,
sets `Host` and the `sni_hostname` extension to the original
hostname. See ADR-009 for full reasoning and the one named limitation
(the `sni_hostname` mechanism is unverified against a real TLS
connection in this sandbox).

## 5. Architecture

```
ExecutionContext (frozen dataclass, plain values only)
        ↓
EngineResolver.resolve(context.engine) -> EngineAdapter
        ↓
EngineAdapter.execute(context) -> ExecutionResult
        │
        ├─ HttpEngineAdapter   — real: httpx + resolve_and_pin, per-hop
        │                        redirect loop, streaming size limit
        ├─ BrowserEngineAdapter — stub: ENGINE_UNSUPPORTED
        └─ ScrapyEngineAdapter  — stub: ENGINE_UNSUPPORTED
```

`ExecutionContext`/`ExecutionResult`/`ExecutionError`/`ErrorCategory`
live in `worker/core/`, independent of `worker/engines/` — an engine
imports the core module, never the reverse. `packages/security/`
depends on nothing in `app.*`/`worker.*` (one-way dependency,
documented in its own `__init__.py`).

## 6. Files Created

- `packages/security/__init__.py`, `packages/security/url_safety.py`
- `apps/worker/worker/core/errors.py`
- `apps/worker/worker/core/execution.py`
- `apps/worker/worker/core/credentials.py`
- `apps/worker/worker/core/logging.py`
- `apps/worker/worker/engines/base.py`
- `apps/worker/worker/engines/resolver.py`
- `apps/worker/worker/engines/http/engine.py`
- `apps/worker/worker/engines/browser/engine.py`
- `apps/worker/worker/engines/scrapy/engine.py`
- `apps/worker/tests/core/test_errors.py`
- `apps/worker/tests/core/test_execution.py`
- `apps/worker/tests/core/test_credentials.py`
- `apps/worker/tests/test_url_safety_shared.py`
- `apps/worker/tests/engines/test_resolver.py`
- `apps/worker/tests/engines/browser/test_browser_stub.py`
- `apps/worker/tests/engines/scrapy/test_scrapy_stub.py`
- `apps/worker/tests/engines/http/test_http_engine_security.py`
- `apps/worker/tests/engines/http/test_http_engine_integration.py`
- `docs/decisions/ADR-008-engine-abstraction.md`
- `docs/decisions/ADR-009-dns-rebinding-ip-pinning.md`
- `docs/architecture/engine-capability-matrix.md`
- `PHASE_3_REPORT.md` (this file)

## 7. Files Modified

- `apps/api/app/core/url_safety.py` — converted to compatibility shim.
- `apps/api/app/schemas/scraper_configuration.py` — added
  `max_response_bytes` field to `HttpEngineConfig` (additive, default
  `20_000_000`, no existing field changed — verified not to break
  `test_scraper_configuration.py`'s assertions by inspection of that
  test's exact assertions, which never enumerate the full field set).
- `docs/architecture/execution-command-contract.md` — added a section
  explaining `ExecutionContext`'s relationship to the still-design-only
  command payload; the payload itself is unchanged.
- `infrastructure/docker/Dockerfile.api`, `Dockerfile.worker` — ship
  `packages/`, extend `PYTHONPATH` (Section 3 above).
- `pyproject.toml` — added `httpx>=0.27` to the `worker` group; added
  `.` to pytest `pythonpath`; broadened the `integration` marker's
  docstring to also cover the example.com test.

No file was deleted. No migration was added or touched. No API
endpoint was added. `apps/scheduler/` was not touched.

## 8. Dependency Changes

- `worker` group: `httpx>=0.27` added.
- **`uv.lock` is NOT regenerated** — attempted `uv lock --offline`,
  which fails (`pydantic was not found in the cache` — the offline
  resolver can't even re-verify already-locked packages without a
  populated cache). This must be run with network access — `uv lock`
  (or just `uv sync --group worker`, which will update the lock as a
  side effect) — before `apps/worker`'s dependency group will
  actually install `httpx`. **This is a required manual/CI step, not
  optional cleanup.**

## 9. SSRF Security

`resolve_and_pin` re-validates on every hop (initial request and
every redirect), using the exact same `is_safe_ip` blocklist as
Phase 2 (loopback/private v4+v6/link-local incl. metadata/multicast/
reserved/unspecified/unsafe scheme). Verified logic (not full
execution) via manual harness: literal metadata IP rejected without a
resolver call, mixed safe/unsafe candidate list rejected (fail-closed),
hostname with no addresses rejected. See Section 16 for exact evidence.

## 10. DNS-Rebinding Mitigation

`resolve_and_pin` calls the resolver exactly once; the HTTP engine
connects to the returned IP directly via `httpx.URL(host=pinned_ip,
...)`, never re-resolving. Verified: a stateful fake resolver that
returns a public IP on its first call and a private IP on every
subsequent call was used to prove `resolve_and_pin` only ever calls it
once (`resolver.call_count == 1`) — both directly (Section 16) and in
a written (not yet executable here) HTTP-engine-level test
(`test_dns_rebinding_does_not_defeat_pinning`).

## 11. Redirect Security

Implemented: manual per-hop loop (`follow_redirects=False` on the
client), `max_redirects` from configuration, visited-URL loop
detection, HTTPS→HTTP downgrade blocking, missing-`Location`
treated as `HTTP_ERROR`. All exercised via written
`httpx.MockTransport`-based tests — **not executable in this
sandbox**, `UNVERIFIED` pending CI.

## 12. Resource Limits

`max_response_bytes` (default 20,000,000, now a real
`HttpEngineConfig` field) enforced by streaming `response.aiter_bytes()`
and aborting the instant the running total exceeds the limit — never
buffering the full body first. Connect timeout `min(5,
timeout_seconds)`; read/write/pool timeout `timeout_seconds`; an
additional wall-clock check before each redirect hop enforces the
overall budget across hops (httpx has no native cross-request
cumulative timeout, so this is a documented approximation). `UNVERIFIED`
pending CI (requires `httpx`).

## 13. Credential Handling

`CredentialProvider` Protocol + `NullCredentialProvider` (always
`None`). The HTTP engine checks `credential_reference` before any
network activity — if set and the provider returns `None`, the result
is `CREDENTIAL_UNAVAILABLE`/`retryable=False` and no request is ever
built. Verified directly (Section 16: `NullCredentialProvider`
returns `None`) and via a written HTTP-engine test asserting the mock
transport is never invoked (`_refusing_handler` raises if called) —
`UNVERIFIED` pending CI for the engine-level assertion.

## 14. Observability

`worker/core/logging.py` mirrors the API's structlog processor chain
exactly. Events: `engine_execution_started`, `engine_execution_completed`,
`engine_execution_failed`, `ssrf_blocked` — all four wired into
`HttpEngineAdapter.execute`. No secret values are ever passed as log
fields (credential values, Authorization/Cookie headers are never
logged). `UNVERIFIED` (requires `structlog`) — not exercised in this
sandbox.

## 15. Testing

19 test functions across `apps/worker/tests/core/` and
`test_url_safety_shared.py` were **actually run** (via a small,
hand-written pytest-compatible shim implementing `pytest.raises` and
`pytest.mark.parametrize`, since real `pytest` isn't installed) — see
Section 16 for the exact run and count. All passed.

The remaining test files (`test_resolver.py`, `test_browser_stub.py`,
`test_scrapy_stub.py`, `test_http_engine_security.py`,
`test_http_engine_integration.py`) import `httpx` and/or `structlog`
at module level and could not be executed in this sandbox at all
(not even via the manual shim — the import itself fails). They are
written to the same standard and will run under the project's real
`pytest` once dependencies are installed (CI, or any environment with
network).

## 16. Security Test Evidence (what was actually run, verbatim summary)

Two real executions, both via `PYTHONPATH` manipulation and — for the
pytest-dependent files — a minimal hand-rolled shim providing
`pytest.raises`/`pytest.mark.parametrize`/`pytest.mark.asyncio`
(passthrough):

1. **Standalone script** (no shim needed — plain asserts) exercising
   `packages.security.url_safety` directly: import identity between
   the API shim and the shared module; `is_safe_ip` on loopback/
   metadata/public; `validate_target_url` accept/reject; `resolve_and_pin`
   happy path, default-port inference, fail-closed on mixed
   candidates, literal dangerous IP rejection. **Result: "ALL SANITY
   CHECKS PASSED."**
2. **Shimmed pytest run** of `test_url_safety_shared.py` (7 test
   functions after parametrize expansion), `test_errors.py` (7),
   `test_execution.py` (7), `test_credentials.py` (1) — **22 total,
   all passed**, including the DNS-rebinding single-resolution proof
   and the full retryability matrix.

Everything in Sections 10-14 above beyond this is `UNVERIFIED`, not
`PASS` — this section is the line between the two.

## 17. Browser Status

`INTERFACE ONLY`. `BrowserEngineAdapter.execute` always returns
`success=False`, `ErrorCategory.ENGINE_UNSUPPORTED`, `retryable=False`.
No Playwright installed or imported. Tested (`test_browser_stub.py`)
but not executable in this sandbox (imports nothing beyond stdlib +
project code, in fact — re-check: it imports `pytest` only, which
also isn't installed here — `UNVERIFIED`, though the code itself has
no third-party runtime dependency and is low-risk).

## 18. Scrapy Status

`INTERFACE ONLY`, identical shape to Browser. Same test-execution
caveat as Section 17.

## 19. Validation Results

Updated after the first real run on a development machine and on GitHub
Actions (PR `phase-3-engine`, merged into `main`).

| Check | Status | Evidence |
|---|---|---|
| `uv lock` / `uv sync` (api, worker, scheduler, dev) | **PASS** | lock regenerated, 65 packages installed incl. `httpx 0.28.1` |
| `ruff check` | **PASS** | "All checks passed!" (after auto-fix of import order / line length) |
| `ruff format` | **PASS** | no files left to reformat |
| `mypy apps/` | **PASS** | "no issues found in 92 source files" (after fixing 8 real errors) |
| Unit tests (worker + API unit) | **PASS** | 135 passed, 1 deselected (`integration`) |
| HTTP engine security tests (`MockTransport`) | **PASS** | 18 tests: SSRF, DNS-rebinding, redirects, loop, downgrade, size, headers, credentials, timeouts |
| Phase 2 regression (`test_url_safety.py` via shim) | **PASS** | all API URL-safety tests still green |
| Real `https://example.com/` integration test | **PASS** | local run: real DNS + pinned IP + SNI + TLS verification succeeded |
| GitHub Actions CI (Postgres + Redis, alembic up/down/up, pytest --cov) | **PASS** | PR checks green, merged |
| `docker build` of `Dockerfile.api` / `Dockerfile.worker` | **UNVERIFIED at authoring; later PASS** | not run when this report was written. Later verified by the maintainer on a Docker-capable machine: both images build and import the shared `packages/` module (maintainer-reported, not re-run in Phase 4) |

Bugs found only by real execution (all fixed): `async with response:` is
invalid for `httpx.Response` (replaced by `contextlib.aclosing`),
`transport` typed as sync `BaseTransport` instead of `AsyncBaseTransport`,
and five mypy typing errors in `worker/core/logging.py`.

Not proven even now: the MockTransport tests do not assert that the socket
connects to `pinned_ip`; that is only indirectly supported by the passing
`example.com` test. Local Python was 3.14, CI uses 3.12 (CI green).

## 20. Known Limitations

- `uv.lock` needs a network-connected `uv lock` run before the worker
  image can actually install `httpx` (Section 8).
- The `sni_hostname` httpx/httpcore extension mechanism ADR-009's
  IP-pinning relies on has not been exercised against a real TLS
  connection (ADR-009's own "Known limitation" section).
- `_classify_connect_error`'s TLS-vs-connection-failure distinction is
  best-effort (inspects `exc.__cause__` for `ssl.SSLError`) and
  unverified against a real failure.
- The overall execution timeout budget across redirect hops is a
  wall-clock approximation (checked before each hop), not a true
  cumulative httpx-level timeout — documented in the engine module.
- No real integration test run against `example.com` — written,
  marked `@pytest.mark.integration`, not executed (no network).

## 21. Residual Risks

- Because dependency-level execution is entirely unverified, there is
  a nonzero chance CI surfaces an integration bug this review
  couldn't catch — e.g. a subtle httpx API mismatch in how
  `extensions={"sni_hostname": ...}` interacts with `verify=True`, or
  in how `httpx.URL(host=..., raw_path=...)` construction behaves for
  edge-case URLs (empty path, unusual query encoding). The pure-logic
  tests (Section 16) reduce but do not eliminate this risk.
- `resolve_and_pin` uses the *first* validated candidate IP when a
  hostname resolves to multiple addresses; this is a deliberate,
  simple choice (not documented as a requirement either way in the
  handoff) but means a hostname with mixed A records where the first
  IP happens to be, e.g., temporarily unreachable, doesn't fail over
  to a second one within Phase 3 — no retry/failover logic exists at
  this layer by design.

## 22. Phase 4 Handoff

- `EngineResolver`/`EngineAdapter`/`ExecutionContext` are ready to be
  driven by real dispatch code once a `jobs` table and queue exist —
  see `docs/architecture/execution-command-contract.md`'s new section
  on the relationship between the (still-design-only) command payload
  and `ExecutionContext`.
- `is_retryable`/`is_retryable_http_error` exist as pure
  classification for Phase 4/5's retry orchestration to consume — no
  retry behavior exists yet.
- A real secret-backend `CredentialProvider` is needed before any
  scraper with `credential_reference` set can execute.
- Before considering Phase 3 "done" in the operational sense: run `uv
  lock` with network access, then `uv sync --group worker --group dev
  --group api`, then the full test suite + ruff + mypy, and update
  this report's Section 19 from `UNVERIFIED` to `PASS`/`FAIL` based on
  actual results.

## 23. Out-of-Scope Confirmation

Confirmed NOT added: `jobs`/`scrape_runs` tables or any migration,
Celery scraping task, queue dispatch, scheduler changes, retry
orchestration, `POST /execute` or any new endpoint, real
Playwright/Scrapy implementation, proxy support, `robots.txt`
handling, HTML parsing/BeautifulSoup/lxml, a real credential secret
backend, authentication/authorization changes, frontend changes.
`apps/scheduler/` was not touched (Section 19 diff review).
