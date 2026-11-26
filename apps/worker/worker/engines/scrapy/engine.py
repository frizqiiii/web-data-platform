"""Scrapy engine — interface only (Phase 3 Decision #2).

Scrapy is NOT installed and no crawl happens here. Same rationale as
`worker.engines.browser.engine.BrowserEngineAdapter` — a real
implementation is a future increment once Scrapy's actual runtime
behavior (its own connection pooling, its own redirect handling,
which would need to be reconciled with or replaced by this
platform's SSRF/IP-pinning requirements) can be verified against real
usage, not assumed.

Future security design (NOT implemented — recorded here so the
future increment doesn't have to re-derive it):

- SSRF validation must be enforced via a Scrapy Downloader
  Middleware that calls the same `packages.security.url_safety.
  resolve_and_pin` this HTTP engine uses, on every request Scrapy's
  scheduler dispatches — including requests discovered by Scrapy's
  own link-following/redirect-following, not just the initial
  request built from `ExecutionContext.url`.
- `obey_robots_txt` (already a field on `ScrapyEngineConfig`, Phase
  2) is a crawling-politeness setting, not a security control, and
  must not be treated as a substitute for SSRF validation.
- Scrapy's default connection reuse/DNS caching must be disabled or
  overridden in the same way the HTTP engine avoids cross-target
  connection pooling — otherwise Scrapy's own resolver, not
  `resolve_and_pin`, ends up being the thing that actually decides
  which IP gets connected to.
"""

from datetime import UTC, datetime

from worker.core.errors import ErrorCategory
from worker.core.execution import ExecutionContext, ExecutionError, ExecutionResult


class ScrapyEngineAdapter:
    async def execute(self, context: ExecutionContext) -> ExecutionResult:
        start = datetime.now(UTC)
        duration_ms = int((datetime.now(UTC) - start).total_seconds() * 1000)
        return ExecutionResult(
            success=False,
            engine="SCRAPY",
            final_url=None,
            http_status=None,
            content_type=None,
            response_size_bytes=None,
            duration_ms=duration_ms,
            safe_response_headers={},
            error=ExecutionError(
                category=ErrorCategory.ENGINE_UNSUPPORTED,
                message=(
                    "Scrapy engine execution is not implemented in Phase 3 — "
                    "interface/stub only. See worker/engines/scrapy/engine.py "
                    "for the recorded future security design."
                ),
                retryable=False,
            ),
        )
