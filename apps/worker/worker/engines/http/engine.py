"""HTTP engine — the one real engine implementation in Phase 3.

Design constraints (all deliberate, see Phase 3 spec Sections 15-19):

- GET only. No other HTTP method is in scope.
- `follow_redirects=False` on the underlying client — redirects are
  followed by THIS module's own loop, one hop at a time, because
  each hop must be independently SSRF-validated and IP-pinned.
  httpx's built-in redirect following has no hook for that.
- TLS verification is always on; never disabled, even for a pinned
  IP connection (see `_build_request`).
- No proxy support, no persistent cookies (a fresh, cookie-less
  client is used per top-level execution — see `execute`).
- `max_keepalive_connections=0`: connection pooling across
  different targets/hops must not be able to reuse a connection
  whose identity (pinned IP, in particular) belonged to a different,
  already-validated hostname. Trade-off: every request pays full
  TCP+TLS handshake cost — no connection reuse at all, even within
  a single execution's redirect chain. This is the safe default for
  Phase 3; a future increment could relax this per-hostname (reusing
  a connection only when consecutive hops share the same *validated*
  pinned IP) if handshake cost becomes a measured problem, but that
  is speculative optimization not needed to correctly implement
  Phase 3's scope.

IP pinning mechanism: each request is built with the connection
`url` pointing at `PinnedTarget.pinned_ip` (not the hostname), while
`Host` header and TLS SNI are explicitly forced to
`PinnedTarget.hostname` via the `sni_hostname` request extension
httpx/httpcore expose for exactly this "connect to a specific IP,
but present/verify a different hostname" scenario. This is the
mechanism ADR-009 requires: connecting to a hostname's resolved
address *without* triggering ANOTHER DNS resolution (and therefore
another chance for DNS-rebinding) at connect time — httpx/httpcore's
normal path would re-resolve the hostname itself when handed a URL
built from `hostname`, which is exactly the TOCTOU window pinning
exists to close.

NOTE ON VERIFICATION: this module cannot be executed in the sandbox
this code was authored in (no network access to install httpx — see
PHASE_3_REPORT.md). The `sni_hostname` extension name/behavior is
based on httpx/httpcore's documented IP-pinning mechanism, but has
NOT been exercised against a real TLS connection here. Treat the TLS
hostname-verification behavior specifically as UNVERIFIED until
CI (which does have network) runs `apps/worker/tests`.
"""

import time
from urllib.parse import urljoin, urlparse

import httpx
from worker.core.credentials import CredentialProvider, NullCredentialProvider
from worker.core.errors import ErrorCategory, is_retryable_http_error
from worker.core.execution import ExecutionContext, ExecutionError, ExecutionResult
from worker.core.logging import (
    get_engine_logger,
    log_engine_execution_completed,
    log_engine_execution_failed,
    log_engine_execution_started,
    log_ssrf_blocked,
)

from packages.security.url_safety import (
    HostnameResolver,
    PinnedTarget,
    UnsafeURLError,
    resolve_and_pin,
)

DEFAULT_MAX_RESPONSE_BYTES = 20_000_000
DEFAULT_MAX_REDIRECTS = 5
_SAFE_RESPONSE_HEADERS = {"content-type", "content-length", "last-modified", "etag"}
_REJECTED_CONFIG_HEADER_NAMES = {"host", "authorization"}
_REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}


class HttpEngineAdapter:
    def __init__(
        self,
        credential_provider: CredentialProvider | None = None,
        resolver: HostnameResolver | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._credential_provider = credential_provider or NullCredentialProvider()
        # Both injected only by tests (a fake DNS resolver, and an
        # httpx.MockTransport that intercepts at the transport layer
        # so tests can exercise redirect/size-limit/header logic
        # deterministically, with no real network — see
        # apps/worker/tests/engines/http/test_http_engine_security.py).
        # Production always uses the real SystemResolver + httpx's
        # real transport (both defaults, via None).
        self._resolver = resolver
        self._transport = transport

    async def execute(self, context: ExecutionContext) -> ExecutionResult:
        start = time.monotonic()
        logger = get_engine_logger()
        log_fields = {
            "execution_id": context.execution_id,
            "organization_id": context.organization_id,
            "project_id": context.project_id,
            "scraper_id": context.scraper_id,
            "target_id": context.target_id,
            "engine": "HTTP",
        }
        log_engine_execution_started(logger, **log_fields)

        try:
            result = await self._execute_inner(context, start)
        except Exception:
            # A genuine bug, not a classified condition — Section 13
            # ("unexpected programming/runtime bugs may still raise")
            # applies. Log what we can before letting it propagate.
            duration_ms = _elapsed_ms(start)
            log_engine_execution_failed(
                logger, duration_ms=duration_ms, error_category="UNCLASSIFIED", **log_fields
            )
            raise

        duration_ms = result.duration_ms
        if result.success:
            log_engine_execution_completed(logger, duration_ms=duration_ms, **log_fields)
        else:
            assert result.error is not None
            if result.error.category == ErrorCategory.SSRF_BLOCKED:
                log_ssrf_blocked(logger, error_category=result.error.category.value, **log_fields)
            log_engine_execution_failed(
                logger,
                duration_ms=duration_ms,
                error_category=result.error.category.value,
                **log_fields,
            )
        return result

    async def _execute_inner(self, context: ExecutionContext, start: float) -> ExecutionResult:
        # --- 1. credential fail-closed, before any network activity ---
        credential_reference = context.credential_reference
        credential_value: str | None = None
        if credential_reference is not None:
            credential_value = await self._credential_provider.get_credential(credential_reference)
            if credential_value is None:
                return self._fail(
                    context,
                    start,
                    ErrorCategory.CREDENTIAL_UNAVAILABLE,
                    f"no credential available for reference {credential_reference!r}",
                    retryable=False,
                )

        # --- 2. build the (static, per-execution) headers ---
        config = context.configuration or {}
        headers: dict[str, str] = {}
        user_agent = config.get("user_agent")
        if user_agent:
            headers["User-Agent"] = user_agent
        config_headers = config.get("headers") or {}
        for key, value in config_headers.items():
            if key.lower() in _REJECTED_CONFIG_HEADER_NAMES:
                # Silently excluded, not a fatal error — Section 21:
                # "Configuration headers can be used. But: Host,
                # Authorization must not be accepted as raw user
                # configuration." The rest of the configured headers
                # are still honored.
                continue
            headers[key] = value
        if credential_value is not None:
            # CredentialProvider is assumed to return a ready-to-use
            # Authorization header value (e.g. "Bearer <token>") —
            # this is the ONLY source of the Authorization header;
            # a configured one is always dropped above.
            headers["Authorization"] = credential_value

        max_redirects = int(config.get("max_redirects", DEFAULT_MAX_REDIRECTS))
        max_response_bytes = int(config.get("max_response_bytes", DEFAULT_MAX_RESPONSE_BYTES))
        connect_timeout = min(5, context.timeout_seconds)
        timeout = httpx.Timeout(
            connect=connect_timeout,
            read=context.timeout_seconds,
            write=context.timeout_seconds,
            pool=context.timeout_seconds,
        )

        current_url = context.url
        visited: set[str] = set()
        limits = httpx.Limits(max_keepalive_connections=0, max_connections=1)

        async with httpx.AsyncClient(
            timeout=timeout,
            limits=limits,
            follow_redirects=False,
            verify=True,
            trust_env=False,  # no proxy — Section 15
            transport=self._transport,
        ) as client:
            for hop in range(max_redirects + 1):
                if _elapsed_ms(start) > context.timeout_seconds * 1000:
                    return self._fail(
                        context,
                        start,
                        ErrorCategory.CONNECTION_TIMEOUT,
                        "overall execution timeout budget exceeded before this hop",
                        retryable=True,
                    )

                normalized = _normalize_url(current_url)
                if normalized in visited:
                    return self._fail(
                        context,
                        start,
                        ErrorCategory.REDIRECT_BLOCKED,
                        f"redirect loop detected at {current_url!r}",
                        retryable=False,
                    )
                visited.add(normalized)

                try:
                    pinned = resolve_and_pin(current_url, resolver=self._resolver)
                except UnsafeURLError as exc:
                    return self._fail(
                        context,
                        start,
                        ErrorCategory.SSRF_BLOCKED,
                        str(exc),
                        retryable=False,
                    )

                try:
                    response = await self._send_one(client, pinned, headers)
                except httpx.ConnectTimeout:
                    return self._fail(
                        context,
                        start,
                        ErrorCategory.CONNECTION_TIMEOUT,
                        f"connect timeout to {pinned.hostname}",
                        retryable=True,
                    )
                except httpx.ReadTimeout:
                    return self._fail(
                        context,
                        start,
                        ErrorCategory.READ_TIMEOUT,
                        f"read timeout from {pinned.hostname}",
                        retryable=True,
                    )
                except httpx.ConnectError as exc:
                    category, message = _classify_connect_error(exc, pinned.hostname)
                    return self._fail(
                        context,
                        start,
                        category,
                        message,
                        retryable=(category == ErrorCategory.CONNECTION_FAILURE),
                    )

                async with response:
                    if response.status_code in _REDIRECT_STATUS_CODES:
                        location = response.headers.get("location")
                        if not location:
                            return self._fail(
                                context,
                                start,
                                ErrorCategory.HTTP_ERROR,
                                f"{response.status_code} redirect with no Location header",
                                retryable=False,
                            )
                        next_url = urljoin(current_url, location)
                        next_scheme = urlparse(next_url).scheme
                        if urlparse(current_url).scheme == "https" and next_scheme == "http":
                            return self._fail(
                                context,
                                start,
                                ErrorCategory.REDIRECT_BLOCKED,
                                "blocked HTTPS -> HTTP downgrade redirect",
                                retryable=False,
                            )
                        if hop == max_redirects:
                            return self._fail(
                                context,
                                start,
                                ErrorCategory.REDIRECT_BLOCKED,
                                f"exceeded max_redirects={max_redirects}",
                                retryable=False,
                            )
                        current_url = next_url
                        continue

                    # Final (non-redirect) response for this execution.
                    try:
                        size = await _drain_with_limit(response, max_response_bytes)
                    except _ResponseTooLarge:
                        return self._fail(
                            context,
                            start,
                            ErrorCategory.RESPONSE_TOO_LARGE,
                            f"response exceeded max_response_bytes={max_response_bytes}",
                            retryable=False,
                        )

                    safe_headers = {
                        name: value
                        for name, value in response.headers.items()
                        if name.lower() in _SAFE_RESPONSE_HEADERS
                    }
                    duration_ms = _elapsed_ms(start)

                    # final_url is current_url (the hostname-based URL for
                    # this hop), NOT response.url — response.url would
                    # report the pinned IP we actually connected to
                    # (host=pinned.pinned_ip), which is an internal
                    # implementation detail that must never leak into a
                    # result a caller might log, store, or display.
                    if 200 <= response.status_code < 300:
                        return ExecutionResult(
                            success=True,
                            engine="HTTP",
                            final_url=current_url,
                            http_status=response.status_code,
                            content_type=safe_headers.get("content-type"),
                            response_size_bytes=size,
                            duration_ms=duration_ms,
                            safe_response_headers=safe_headers,
                            error=None,
                        )

                    retryable = is_retryable_http_error(response.status_code)
                    return ExecutionResult(
                        success=False,
                        engine="HTTP",
                        final_url=current_url,
                        http_status=response.status_code,
                        content_type=safe_headers.get("content-type"),
                        response_size_bytes=size,
                        duration_ms=duration_ms,
                        safe_response_headers=safe_headers,
                        error=ExecutionError(
                            category=ErrorCategory.HTTP_ERROR,
                            message=f"upstream returned HTTP {response.status_code}",
                            retryable=retryable,
                        ),
                    )

        # Loop exhausted without returning — shouldn't be reachable given
        # the max_redirects check above, but fail closed rather than
        # falling off the end silently.
        return self._fail(
            context,
            start,
            ErrorCategory.REDIRECT_BLOCKED,
            f"exceeded max_redirects={max_redirects}",
            retryable=False,
        )

    async def _send_one(
        self, client: httpx.AsyncClient, pinned: PinnedTarget, headers: dict[str, str]
    ) -> httpx.Response:
        parsed = urlparse(pinned.url)
        path = parsed.path or "/"
        pinned_url = httpx.URL(
            scheme=pinned.scheme,
            host=pinned.pinned_ip,
            port=pinned.port,
            raw_path=(path + (("?" + parsed.query) if parsed.query else "")).encode(),
        )
        request_headers = {**headers, "Host": pinned.hostname}
        extensions = {"sni_hostname": pinned.hostname} if pinned.scheme == "https" else {}
        request = client.build_request(
            "GET", pinned_url, headers=request_headers, extensions=extensions
        )
        return await client.send(request, stream=True)

    def _fail(
        self,
        context: ExecutionContext,
        start: float,
        category: ErrorCategory,
        message: str,
        *,
        retryable: bool,
    ) -> ExecutionResult:
        return ExecutionResult(
            success=False,
            engine="HTTP",
            final_url=None,
            http_status=None,
            content_type=None,
            response_size_bytes=None,
            duration_ms=_elapsed_ms(start),
            safe_response_headers={},
            error=ExecutionError(category=category, message=message, retryable=retryable),
        )


class _ResponseTooLarge(Exception):
    pass


async def _drain_with_limit(response: httpx.Response, max_bytes: int) -> int:
    """Streams the (already-decompressed, per httpx's transport-level
    content decoding) response body, counting bytes as they arrive,
    and aborts the instant the limit is crossed — never buffering the
    full body first and checking size after."""
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > max_bytes:
            raise _ResponseTooLarge()
    return total


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


def _normalize_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path or '/'}?{parsed.query}"


def _classify_connect_error(exc: httpx.ConnectError, hostname: str) -> tuple[ErrorCategory, str]:
    """Best-effort classification of a connect-level failure into
    TLS_FAILURE vs. CONNECTION_FAILURE. httpx wraps the underlying
    ssl.SSLError as the __cause__ of its own ConnectError rather than
    raising a distinct TLS-specific exception type, so this inspects
    the cause chain rather than the exception type. UNVERIFIED
    against a real TLS failure in this sandbox (see module docstring)
    — the fallback (CONNECTION_FAILURE) is safe either way, since
    both categories already treat the failure conservatively
    (TLS_FAILURE non-retryable, CONNECTION_FAILURE retryable — a
    misclassified retryable connection failure just costs one wasted
    retry, it does not weaken any security check)."""
    import ssl

    cause = exc.__cause__
    if isinstance(cause, ssl.SSLError):
        return ErrorCategory.TLS_FAILURE, f"TLS failure connecting to {hostname}: {cause}"
    return ErrorCategory.CONNECTION_FAILURE, f"connection failure to {hostname}: {exc}"
