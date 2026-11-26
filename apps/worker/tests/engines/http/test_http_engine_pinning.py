"""Proves the HTTP engine connects to the PINNED IP, not the hostname.

The existing security tests use httpx.MockTransport and only assert on the
Host header. These tests additionally assert on what the transport actually
receives as the connection target (request.url.host) and on the TLS SNI
extension, which is the evidence that DNS-rebinding pinning works.
"""

from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from worker.core.execution import ExecutionContext
from worker.engines.http.engine import HttpEngineAdapter


class _FakeResolver:
    def __init__(self, mapping: dict[str, list[str]]) -> None:
        self._mapping = mapping
        self.calls: list[str] = []

    def resolve(self, hostname: str) -> list[str]:
        self.calls.append(hostname)
        return self._mapping.get(hostname, [])


def _context(url: str) -> ExecutionContext:
    return ExecutionContext(
        execution_id=uuid4(),
        organization_id=uuid4(),
        project_id=uuid4(),
        scraper_id=uuid4(),
        target_id=uuid4(),
        scraper_version=1,
        engine="HTTP",
        configuration={},
        url=url,
        requested_at=datetime.now(UTC),
        timeout_seconds=30,
    )


@pytest.mark.asyncio
async def test_https_request_connects_to_pinned_ip_with_original_hostname_sni() -> None:
    resolver = _FakeResolver({"pinned.example.test": ["93.184.216.34"]})
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"ok")

    adapter = HttpEngineAdapter(resolver=resolver, transport=httpx.MockTransport(handler))
    result = await adapter.execute(_context("https://pinned.example.test/path?q=1"))

    assert result.success is True
    assert len(seen) == 1
    request = seen[0]
    # The connection target is the validated IP, never the hostname.
    assert request.url.host == "93.184.216.34"
    assert request.url.port in (None, 443)
    # Host header and TLS SNI keep the original hostname.
    assert request.headers["host"] == "pinned.example.test"
    assert request.extensions.get("sni_hostname") == "pinned.example.test"
    # The path and query survive pinning.
    assert request.url.path == "/path"
    assert request.url.query == b"q=1"
    # The hostname is resolved exactly once for this hop.
    assert resolver.calls == ["pinned.example.test"]
    # The pinned IP never leaks into the result.
    assert result.final_url == "https://pinned.example.test/path?q=1"


@pytest.mark.asyncio
async def test_each_redirect_hop_is_pinned_to_its_own_validated_ip() -> None:
    resolver = _FakeResolver(
        {"a.example.test": ["93.184.216.34"], "b.example.test": ["93.184.216.35"]}
    )
    connected_hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        connected_hosts.append(request.url.host)
        if request.headers["host"] == "a.example.test":
            return httpx.Response(302, headers={"location": "https://b.example.test/"})
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"ok")

    adapter = HttpEngineAdapter(resolver=resolver, transport=httpx.MockTransport(handler))
    result = await adapter.execute(_context("https://a.example.test/"))

    assert result.success is True
    assert connected_hosts == ["93.184.216.34", "93.184.216.35"]
    assert resolver.calls == ["a.example.test", "b.example.test"]


@pytest.mark.asyncio
async def test_plain_http_request_is_pinned_and_sets_no_sni() -> None:
    resolver = _FakeResolver({"plain.example.test": ["93.184.216.34"]})
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"ok")

    adapter = HttpEngineAdapter(resolver=resolver, transport=httpx.MockTransport(handler))
    result = await adapter.execute(_context("http://plain.example.test:8080/"))

    assert result.success is True
    assert seen[0].url.host == "93.184.216.34"
    assert seen[0].url.port == 8080
    assert "sni_hostname" not in seen[0].extensions
