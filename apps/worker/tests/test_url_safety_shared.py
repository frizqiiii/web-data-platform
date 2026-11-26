"""Tests for packages.security.url_safety's worker-relevant surface:
`resolve_and_pin` and the DNS-rebinding scenario it exists to close.

`validate_target_url`/`is_safe_ip` already have full coverage in
apps/api/tests/unit/test_url_safety.py against the SAME shared
module (via the API's compatibility shim) — not duplicated here.
"""

import pytest

from packages.security.url_safety import PinnedTarget, UnsafeURLError, resolve_and_pin


class _FakeResolver:
    def __init__(self, mapping: dict[str, list[str]]) -> None:
        self._mapping = mapping

    def resolve(self, hostname: str) -> list[str]:
        return self._mapping.get(hostname, [])


class _StatefulRebindingResolver:
    """Simulates DNS rebinding: the FIRST resolve() call for a given
    hostname returns a public IP; every subsequent call for the same
    hostname returns a private IP. This proves `resolve_and_pin`
    resolves exactly once and callers must reuse the returned
    `pinned_ip` rather than resolving the hostname a second time —
    if production code (or a test) resolved twice, it would get the
    dangerous second answer.
    """

    def __init__(self, first_ip: str, rebind_ip: str) -> None:
        self._first_ip = first_ip
        self._rebind_ip = rebind_ip
        self.call_count = 0

    def resolve(self, hostname: str) -> list[str]:
        self.call_count += 1
        return [self._first_ip] if self.call_count == 1 else [self._rebind_ip]


def test_resolve_and_pin_returns_validated_ip_and_original_hostname() -> None:
    resolver = _FakeResolver({"public.example.test": ["93.184.216.34"]})
    pinned = resolve_and_pin("https://public.example.test:8443/page?x=1", resolver=resolver)
    assert isinstance(pinned, PinnedTarget)
    assert pinned.hostname == "public.example.test"
    assert pinned.pinned_ip == "93.184.216.34"
    assert pinned.port == 8443
    assert pinned.scheme == "https"
    assert pinned.url == "https://public.example.test:8443/page?x=1"


@pytest.mark.parametrize(
    ("url", "expected_port"),
    [
        ("http://example.test/", 80),
        ("https://example.test/", 443),
    ],
)
def test_resolve_and_pin_infers_default_port(url: str, expected_port: int) -> None:
    resolver = _FakeResolver({"example.test": ["93.184.216.34"]})
    pinned = resolve_and_pin(url, resolver=resolver)
    assert pinned.port == expected_port


def test_resolve_and_pin_rejects_literal_dangerous_ip_with_no_resolver_call() -> None:
    with pytest.raises(UnsafeURLError):
        resolve_and_pin("http://169.254.169.254/latest/meta-data/")


def test_resolve_and_pin_fails_closed_on_any_unsafe_candidate() -> None:
    resolver = _FakeResolver({"mixed.example.test": ["93.184.216.34", "127.0.0.1"]})
    with pytest.raises(UnsafeURLError):
        resolve_and_pin("http://mixed.example.test/", resolver=resolver)


def test_resolve_and_pin_rejects_hostname_with_no_addresses() -> None:
    resolver = _FakeResolver({})
    with pytest.raises(UnsafeURLError):
        resolve_and_pin("http://nowhere.example.test/", resolver=resolver)


def test_dns_rebinding_resolve_and_pin_only_resolves_once() -> None:
    """The core DNS-rebinding-mitigation proof: even though the
    resolver would return a dangerous private IP on a SECOND call,
    resolve_and_pin only calls it once, so the returned PinnedTarget
    carries the (safe) first answer, and the resolver was invoked
    exactly once."""
    resolver = _StatefulRebindingResolver(first_ip="93.184.216.34", rebind_ip="10.0.0.1")
    pinned = resolve_and_pin("http://rebinding.example.test/", resolver=resolver)
    assert pinned.pinned_ip == "93.184.216.34"
    assert resolver.call_count == 1


def test_dns_rebinding_a_naive_resolve_then_reresolve_pipeline_would_be_unsafe() -> None:
    """Negative control proving the vulnerability resolve_and_pin
    closes is real: calling the resolver a SECOND time for the same
    hostname (simulating a "validate, then let the HTTP client
    re-resolve by hostname" pipeline) does return the dangerous
    address. This test exists to document *why* resolve_and_pin's
    single-resolution design matters, not to test resolve_and_pin
    itself."""
    resolver = _StatefulRebindingResolver(first_ip="93.184.216.34", rebind_ip="10.0.0.1")
    resolver.resolve("rebinding.example.test")  # first call: public IP
    second_answer = resolver.resolve("rebinding.example.test")  # second call: rebound
    assert second_answer == ["10.0.0.1"]
