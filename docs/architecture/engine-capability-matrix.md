# Engine Capability Matrix

Status as of Phase 3 (Scraping Engine & Execution Foundation). See
ADR-008 (engine abstraction, Browser/Scrapy deferral) and ADR-009
(DNS-rebinding/IP-pinning) for the reasoning behind these decisions.

Status legend:

- **IMPLEMENTED** — real code exists and does the described work.
- **INTERFACE ONLY** — an `EngineAdapter` exists and can be dispatched
  to, but it does not perform the underlying operation; it returns a
  classified `ENGINE_UNSUPPORTED` result.
- **DESIGNED** — documented (in code comments/ADRs) as the intended
  future behavior, but no code exists yet.
- **UNVERIFIED** — code exists and is believed correct, but has not
  actually been executed/observed to work in any environment yet.
- **NOT IN SCOPE** — intentionally deferred to a later phase.

## Per-engine status

| Engine  | Execution | SSRF re-validation | IP-pinning / DNS-rebinding | Redirect handling | Notes |
|---------|-----------|---------------------|------------------------------|--------------------|-------|
| HTTP    | IMPLEMENTED (logic) / UNVERIFIED (execution) | IMPLEMENTED (logic) / UNVERIFIED (execution) | IMPLEMENTED (logic) / UNVERIFIED (execution) | IMPLEMENTED (logic) / UNVERIFIED (execution) | See "Why HTTP is split" below. |
| BROWSER | INTERFACE ONLY | NOT IN SCOPE | NOT IN SCOPE | NOT IN SCOPE | Always returns `ENGINE_UNSUPPORTED`. Future security design documented in `worker/engines/browser/engine.py` and ADR-008. |
| SCRAPY  | INTERFACE ONLY | NOT IN SCOPE | NOT IN SCOPE | NOT IN SCOPE | Always returns `ENGINE_UNSUPPORTED`. Future security design documented in `worker/engines/scrapy/engine.py` and ADR-008. |

## Why HTTP is split into "logic" vs. "execution"

The HTTP engine's code (`worker/engines/http/engine.py`) was written
to fully satisfy the Phase 3 specification, and its pure logic —
everything that doesn't require actually importing/running `httpx` —
was executed and passed via a manual test harness (see
PHASE_3_REPORT.md Section 15/16 for exact evidence): the error
taxonomy, `ExecutionContext`/`ExecutionResult` invariants,
`resolve_and_pin`'s DNS-rebinding-resistant single-resolution
behavior, and the API compatibility shim.

The engine module itself, and everything that depends on `httpx`
actually running (real HTTP requests via `httpx.MockTransport` in
unit tests, the real `sni_hostname`-based IP-pinning mechanism, real
timeout/redirect/size-limit behavior against a transport) could
**not** be executed in the sandbox this was authored in: there is no
network access to install `httpx`, `structlog`, or any other
third-party dependency (verified by attempting `pip install httpx`,
which fails with no matching distribution — see PHASE_3_REPORT.md).

Concretely:

| Capability | Status |
|---|---|
| GET-only, `follow_redirects=False`, manual per-hop redirect loop | IMPLEMENTED / UNVERIFIED |
| TLS verification always on, never disabled | IMPLEMENTED / UNVERIFIED |
| No proxy (`trust_env=False`), no persistent cookies (fresh client per execution) | IMPLEMENTED / UNVERIFIED |
| SSRF re-validation via `resolve_and_pin` on every hop | IMPLEMENTED / UNVERIFIED |
| IP-pinning via `sni_hostname` extension + explicit `Host` header | IMPLEMENTED / UNVERIFIED — see ADR-009's "Known limitation" |
| Redirect loop detection | IMPLEMENTED / UNVERIFIED |
| HTTPS→HTTP downgrade blocking | IMPLEMENTED / UNVERIFIED |
| `max_redirects` enforcement | IMPLEMENTED / UNVERIFIED |
| Streaming response-size limit (`max_response_bytes`, aborts mid-stream) | IMPLEMENTED / UNVERIFIED |
| Connect/read/total timeout handling | IMPLEMENTED / UNVERIFIED |
| Safe response header allowlist (content-type/content-length/last-modified/etag only) | IMPLEMENTED / UNVERIFIED |
| Configured `Host`/`Authorization` headers rejected | IMPLEMENTED / UNVERIFIED |
| `CredentialProvider` fail-closed (no request sent if credential unavailable) | IMPLEMENTED / UNVERIFIED |
| Connection-pool isolation (`max_keepalive_connections=0`) | IMPLEMENTED / UNVERIFIED |
| TLS-failure vs. connection-failure classification | IMPLEMENTED (best-effort) / UNVERIFIED — see engine module docstring on `_classify_connect_error` |

**None of the UNVERIFIED rows above should be read as PASS.** They
become PASS only once `apps/worker/tests/engines/http/` has actually
been run — by CI, or by anyone with network access — and the results
observed.

## Not implemented, by design (NOT IN SCOPE for Phase 3)

- Browser and Scrapy real execution (ADR-008).
- Queue dispatch, scheduler, retry orchestration. (Jobs/scrape_runs
  *persistence* was added in Phase 4 — ADR-010 — but nothing calls it
  yet.) Phase 3 defines `is_retryable`/
  `is_retryable_http_error` as pure classification; nothing acts on
  that classification yet.
- `POST /execute` or any other new API endpoint — Phase 3's
  `EngineResolver`/`EngineAdapter` are invoked only from tests.
- Proxy support, `robots.txt` handling, HTML parsing/data extraction
  (`ErrorCategory.PARSER_FAILURE` exists in the taxonomy for a future
  phase to use; nothing raises it yet).
- A real secret-backend `CredentialProvider` — only `NullCredentialProvider`
  exists, which is why any scraper with `credential_reference` set
  currently cannot execute (`CREDENTIAL_UNAVAILABLE`, by design).
