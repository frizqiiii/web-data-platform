"""Browser engine — interface only (Phase 3 Decision #2).

Playwright is NOT installed and no browser automation happens here.
This adapter exists so `EngineResolver` has something to return for
`engine="BROWSER"` scrapers, and so callers get a classified
`ENGINE_UNSUPPORTED` result instead of a `KeyError` or a crash. Real
browser execution is a future increment, once its runtime
environment (a container with the actual browser binaries, resource
limits appropriate for a headless browser, etc.) can be verified —
building it speculatively now, against an environment nobody has
confirmed, is exactly the "install Playwright to make the checklist
look complete" anti-pattern Phase 3 explicitly rejects.

Future security design (NOT implemented — recorded here so the
future increment doesn't have to re-derive it):

- Every navigation and every sub-request (`page.route("**/*")`
  request interception) must go through the same
  `packages.security.url_safety.resolve_and_pin` this HTTP engine
  uses — a browser's own JS-initiated fetch()/XHR calls are exactly
  as SSRF-capable as the top-level navigation, and redirects inside
  the browser need the same per-hop validation as the HTTP engine's.
- No persistent browser context/profile across executions (no
  cookie/localStorage leakage between different targets or tenants).
- Downloads must be explicitly denied or routed through the same
  response-size/content-type controls as the HTTP engine, not left
  to the browser's default download behavior.
- A page opening a popup or a new tab must be subject to the same
  navigation policy as the original page — not implicitly trusted.
- iframes must be subject to the same per-origin SSRF validation as
  top-level navigation.
- Resource-type filtering (e.g. blocking fonts/media by default) is a
  performance concern, not a security one, and is out of scope for
  the security design itself.
"""

from datetime import UTC, datetime

from worker.core.errors import ErrorCategory
from worker.core.execution import ExecutionContext, ExecutionError, ExecutionResult


class BrowserEngineAdapter:
    async def execute(self, context: ExecutionContext) -> ExecutionResult:
        start = datetime.now(UTC)
        duration_ms = int((datetime.now(UTC) - start).total_seconds() * 1000)
        return ExecutionResult(
            success=False,
            engine="BROWSER",
            final_url=None,
            http_status=None,
            content_type=None,
            response_size_bytes=None,
            duration_ms=duration_ms,
            safe_response_headers={},
            error=ExecutionError(
                category=ErrorCategory.ENGINE_UNSUPPORTED,
                message=(
                    "Browser engine execution is not implemented in Phase 3 — "
                    "interface/stub only. See worker/engines/browser/engine.py "
                    "for the recorded future security design."
                ),
                retryable=False,
            ),
        )
