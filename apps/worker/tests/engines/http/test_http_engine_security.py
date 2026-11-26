"""Security tests for HttpEngineAdapter.

These use httpx.MockTransport to intercept at the transport layer —
no real network, no real DNS. Crucially, this does NOT disable the
SSRF policy: `resolve_and_pin` (and therefore is_safe_ip) still runs
for real on every hop, using an injected fake DNS resolver. The mock
transport only stands in for "what a real server at the validated,
pinned IP would have answered" — the security boundary under test is
never bypassed, only the network underneath it.

NOTE: this module could not be executed in the sandbox this code was
authored in — httpx is not installed there and there is no network
access to install it (see PHASE_3_REPORT.md). It is written to run
under the project's real CI (which does have network). Treat every
scenario below as UNVERIFIED until CI actually runs it.
"""

from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from worker.core.credentials import CredentialProvider
from worker.core.errors import ErrorCategory
from worker.core.execution import ExecutionContext
from worker.engines.http.engine import HttpEngineAdapter


class _FakeResolver:
    def __init__(self, mapping: dict[str, list[str]]) -> None:
        self._mapping = mapping
        self.calls: list[str] = []

    def resolve(self, hostname: str) -> list[str]:
        self.calls.append(hostname)
        return self._mapping.get(hostname, [])


class _StatefulRebindingResolver:
    def __init__(self, first_ip: str, rebind_ip: str) -> None:
        self._first_ip = first_ip
        self._rebind_ip = rebind_ip
        self.call_count = 0

    def resolve(self, hostname: str) -> list[str]:
        self.call_count += 1
        return [self._first_ip] if self.call_count == 1 else [self._rebind_ip]


class _AlwaysGrantingCredentialProvider:
    async def get_credential(self, reference: str) -> str | None:
        return f"Bearer resolved-for-{reference}"


class _NeverGrantingCredentialProvider:
    async def get_credential(self, reference: str) -> str | None:
        return None


def _context(
    url: str,
    *,
    configuration: dict | None = None,
    credential_reference: str | None = None,
    timeout_seconds: int = 30,
) -> ExecutionContext:
    return ExecutionContext(
        execution_id=uuid4(),
        organization_id=uuid4(),
        project_id=uuid4(),
        scraper_id=uuid4(),
        target_id=uuid4(),
        scraper_version=1,
        engine="HTTP",
        configuration=configuration or {},
        url=url,
        requested_at=datetime.now(UTC),
        timeout_seconds=timeout_seconds,
        credential_reference=credential_reference,
    )


def _refusing_handler(request: httpx.Request) -> httpx.Response:
    raise AssertionError(
        f"transport should never have been called — SSRF/credential check "
        f"should have short-circuited before any network attempt (got {request.url!r})"
    )


# --- SSRF: blocked before any request is ever sent ---


@pytest.mark.asyncio
async def test_ssrf_blocked_for_hostname_resolving_to_private_ip() -> None:
    resolver = _FakeResolver({"internal.example.test": ["10.0.0.5"]})
    transport = httpx.MockTransport(_refusing_handler)
    adapter = HttpEngineAdapter(resolver=resolver, transport=transport)

    result = await adapter.execute(_context("http://internal.example.test/"))

    assert result.success is False
    assert result.error is not None
    assert result.error.category == ErrorCategory.SSRF_BLOCKED
    assert result.error.retryable is False


@pytest.mark.asyncio
async def test_ssrf_blocked_for_literal_cloud_metadata_ip() -> None:
    transport = httpx.MockTransport(_refusing_handler)
    adapter = HttpEngineAdapter(transport=transport)

    result = await adapter.execute(_context("http://169.254.169.254/latest/meta-data/"))

    assert result.success is False
    assert result.error is not None
    assert result.error.category == ErrorCategory.SSRF_BLOCKED


# --- DNS rebinding: resolve_and_pin only resolves once per hop ---


@pytest.mark.asyncio
async def test_dns_rebinding_does_not_defeat_pinning() -> None:
    resolver = _StatefulRebindingResolver(first_ip="93.184.216.34", rebind_ip="10.0.0.1")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["host"] == "rebinding.example.test"
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"ok")

    transport = httpx.MockTransport(handler)
    adapter = HttpEngineAdapter(resolver=resolver, transport=transport)

    result = await adapter.execute(_context("http://rebinding.example.test/"))

    assert result.success is True
    assert resolver.call_count == 1  # exactly one resolution for the one hop


# --- Redirects: per-hop re-validation, loop detection, downgrade blocking ---


@pytest.mark.asyncio
async def test_redirect_to_validated_target_is_followed() -> None:
    resolver = _FakeResolver(
        {"hop1.example.test": ["93.184.216.34"], "hop2.example.test": ["93.184.216.35"]}
    )

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.headers["host"]
        if host == "hop1.example.test":
            return httpx.Response(302, headers={"location": "https://hop2.example.test/final"})
        if host == "hop2.example.test":
            return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"done")
        raise AssertionError(f"unexpected host: {host}")

    transport = httpx.MockTransport(handler)
    adapter = HttpEngineAdapter(resolver=resolver, transport=transport)

    result = await adapter.execute(_context("https://hop1.example.test/"))

    assert result.success is True
    assert result.final_url == "https://hop2.example.test/final"
    assert result.http_status == 200


@pytest.mark.asyncio
async def test_redirect_to_private_ip_is_blocked() -> None:
    resolver = _FakeResolver(
        {
            "public-start.example.test": ["93.184.216.34"],
            "internal-target.example.test": ["10.0.0.9"],
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.headers["host"]
        if host == "public-start.example.test":
            return httpx.Response(
                302, headers={"location": "http://internal-target.example.test/secret"}
            )
        raise AssertionError("should never reach the private-IP hop")

    transport = httpx.MockTransport(handler)
    adapter = HttpEngineAdapter(resolver=resolver, transport=transport)

    result = await adapter.execute(_context("http://public-start.example.test/"))

    assert result.success is False
    assert result.error is not None
    assert result.error.category == ErrorCategory.SSRF_BLOCKED


@pytest.mark.asyncio
async def test_redirect_loop_is_detected() -> None:
    resolver = _FakeResolver({"loop.example.test": ["93.184.216.34"]})

    def handler(request: httpx.Request) -> httpx.Response:
        # /a -> /b -> /a -> ... forever
        path = request.url.path
        next_path = "/b" if path in ("/", "/a") else "/a"
        return httpx.Response(302, headers={"location": f"http://loop.example.test{next_path}"})

    transport = httpx.MockTransport(handler)
    adapter = HttpEngineAdapter(resolver=resolver, transport=transport)

    result = await adapter.execute(_context("http://loop.example.test/"))

    assert result.success is False
    assert result.error is not None
    assert result.error.category == ErrorCategory.REDIRECT_BLOCKED


@pytest.mark.asyncio
async def test_https_to_http_downgrade_redirect_is_blocked() -> None:
    resolver = _FakeResolver({"secure.example.test": ["93.184.216.34"]})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://secure.example.test/downgraded"})

    transport = httpx.MockTransport(handler)
    adapter = HttpEngineAdapter(resolver=resolver, transport=transport)

    result = await adapter.execute(_context("https://secure.example.test/"))

    assert result.success is False
    assert result.error is not None
    assert result.error.category == ErrorCategory.REDIRECT_BLOCKED


@pytest.mark.asyncio
async def test_exceeding_max_redirects_is_blocked() -> None:
    resolver = _FakeResolver({"redirector.example.test": ["93.184.216.34"]})
    hop_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        hop_count["n"] += 1
        return httpx.Response(
            302, headers={"location": f"http://redirector.example.test/{hop_count['n']}"}
        )

    transport = httpx.MockTransport(handler)
    adapter = HttpEngineAdapter(resolver=resolver, transport=transport)

    result = await adapter.execute(
        _context("http://redirector.example.test/0", configuration={"max_redirects": 2})
    )

    assert result.success is False
    assert result.error is not None
    assert result.error.category == ErrorCategory.REDIRECT_BLOCKED


# --- Response size limit: aborted while streaming, not after full buffering ---


@pytest.mark.asyncio
async def test_oversized_response_is_rejected() -> None:
    resolver = _FakeResolver({"big.example.test": ["93.184.216.34"]})
    big_body = b"x" * 1000

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "application/octet-stream"}, content=big_body
        )

    transport = httpx.MockTransport(handler)
    adapter = HttpEngineAdapter(resolver=resolver, transport=transport)

    result = await adapter.execute(
        _context("http://big.example.test/", configuration={"max_response_bytes": 100})
    )

    assert result.success is False
    assert result.error is not None
    assert result.error.category == ErrorCategory.RESPONSE_TOO_LARGE
    assert result.error.retryable is False


@pytest.mark.asyncio
async def test_response_within_limit_is_accepted() -> None:
    resolver = _FakeResolver({"small.example.test": ["93.184.216.34"]})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"hi")

    transport = httpx.MockTransport(handler)
    adapter = HttpEngineAdapter(resolver=resolver, transport=transport)

    result = await adapter.execute(
        _context("http://small.example.test/", configuration={"max_response_bytes": 100})
    )

    assert result.success is True
    assert result.response_size_bytes == 2


# --- Header handling: Host/Authorization stripped from config, safe allowlist on the way out ---


@pytest.mark.asyncio
async def test_configured_host_and_authorization_headers_are_dropped() -> None:
    resolver = _FakeResolver({"target.example.test": ["93.184.216.34"]})
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"ok")

    transport = httpx.MockTransport(handler)
    adapter = HttpEngineAdapter(resolver=resolver, transport=transport)

    await adapter.execute(
        _context(
            "http://target.example.test/",
            configuration={
                "headers": {
                    "Host": "attacker-controlled.example.test",
                    "Authorization": "Bearer attacker-supplied-token",
                    "X-Custom": "kept",
                }
            },
        )
    )

    assert len(captured) == 1
    sent = captured[0]
    # Host must be the real pinned hostname, never the attacker-supplied
    # config value (which would break IP-pinning's whole point).
    assert sent.headers["host"] == "target.example.test"
    assert "authorization" not in sent.headers
    assert sent.headers["x-custom"] == "kept"


@pytest.mark.asyncio
async def test_credential_is_the_only_source_of_authorization_header() -> None:
    resolver = _FakeResolver({"secured.example.test": ["93.184.216.34"]})
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"ok")

    transport = httpx.MockTransport(handler)
    provider: CredentialProvider = _AlwaysGrantingCredentialProvider()
    adapter = HttpEngineAdapter(
        credential_provider=provider, resolver=resolver, transport=transport
    )

    result = await adapter.execute(
        _context("http://secured.example.test/", credential_reference="vault://token-123")
    )

    assert result.success is True
    assert captured[0].headers["authorization"] == "Bearer resolved-for-vault://token-123"


@pytest.mark.asyncio
async def test_safe_response_headers_allowlist_excludes_set_cookie() -> None:
    resolver = _FakeResolver({"cookie.example.test": ["93.184.216.34"]})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "content-type": "text/html",
                "set-cookie": "session=super-secret; Path=/",
                "etag": '"abc123"',
            },
            content=b"<html></html>",
        )

    transport = httpx.MockTransport(handler)
    adapter = HttpEngineAdapter(resolver=resolver, transport=transport)

    result = await adapter.execute(_context("http://cookie.example.test/"))

    assert result.success is True
    assert "set-cookie" not in result.safe_response_headers
    assert result.safe_response_headers.get("content-type") == "text/html"
    assert result.safe_response_headers.get("etag") == '"abc123"'


# --- Credential fail-closed: no request attempted at all ---


@pytest.mark.asyncio
async def test_credential_unavailable_is_fail_closed_before_any_request() -> None:
    transport = httpx.MockTransport(_refusing_handler)
    provider: CredentialProvider = _NeverGrantingCredentialProvider()
    adapter = HttpEngineAdapter(credential_provider=provider, transport=transport)

    result = await adapter.execute(
        _context("http://target.example.test/", credential_reference="vault://missing")
    )

    assert result.success is False
    assert result.error is not None
    assert result.error.category == ErrorCategory.CREDENTIAL_UNAVAILABLE
    assert result.error.retryable is False


# --- HTTP status handling: 4xx/5xx are classified but not exceptions ---


@pytest.mark.asyncio
async def test_upstream_4xx_is_http_error_not_retryable() -> None:
    resolver = _FakeResolver({"notfound.example.test": ["93.184.216.34"]})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, headers={"content-type": "text/plain"}, content=b"nope")

    transport = httpx.MockTransport(handler)
    adapter = HttpEngineAdapter(resolver=resolver, transport=transport)

    result = await adapter.execute(_context("http://notfound.example.test/"))

    assert result.success is False
    assert result.http_status == 404
    assert result.error is not None
    assert result.error.category == ErrorCategory.HTTP_ERROR
    assert result.error.retryable is False


@pytest.mark.asyncio
async def test_upstream_5xx_is_http_error_retryable() -> None:
    resolver = _FakeResolver({"broken.example.test": ["93.184.216.34"]})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, headers={"content-type": "text/plain"}, content=b"down")

    transport = httpx.MockTransport(handler)
    adapter = HttpEngineAdapter(resolver=resolver, transport=transport)

    result = await adapter.execute(_context("http://broken.example.test/"))

    assert result.success is False
    assert result.http_status == 503
    assert result.error is not None
    assert result.error.category == ErrorCategory.HTTP_ERROR
    assert result.error.retryable is True


# --- Timeouts: classified, not raised ---


@pytest.mark.asyncio
async def test_connect_timeout_is_classified() -> None:
    resolver = _FakeResolver({"slow.example.test": ["93.184.216.34"]})

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("connect timed out", request=request)

    transport = httpx.MockTransport(handler)
    adapter = HttpEngineAdapter(resolver=resolver, transport=transport)

    result = await adapter.execute(_context("http://slow.example.test/"))

    assert result.success is False
    assert result.error is not None
    assert result.error.category == ErrorCategory.CONNECTION_TIMEOUT
    assert result.error.retryable is True


@pytest.mark.asyncio
async def test_read_timeout_is_classified() -> None:
    resolver = _FakeResolver({"stalls.example.test": ["93.184.216.34"]})

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timed out", request=request)

    transport = httpx.MockTransport(handler)
    adapter = HttpEngineAdapter(resolver=resolver, transport=transport)

    result = await adapter.execute(_context("http://stalls.example.test/"))

    assert result.success is False
    assert result.error is not None
    assert result.error.category == ErrorCategory.READ_TIMEOUT
    assert result.error.retryable is True
