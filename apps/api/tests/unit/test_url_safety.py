"""Unit tests for the SSRF-safe URL validator.

No network/DNS needed — literal-IP URLs are checked directly, and a
fake resolver stands in for DNS-based hostnames.
"""

import pytest
from app.core.url_safety import HostnameResolver, UnsafeURLError, is_safe_ip, validate_target_url


class FakeResolver:
    def __init__(self, mapping: dict[str, list[str]]) -> None:
        self._mapping = mapping

    def resolve(self, hostname: str) -> list[str]:
        return self._mapping.get(hostname, [])


def _fake_resolver(hostname: str, ips: list[str]) -> HostnameResolver:
    return FakeResolver({hostname: ips})


# --- is_safe_ip: pure logic, the core of the SSRF policy ---


@pytest.mark.parametrize(
    "ip_str",
    [
        "127.0.0.1",  # loopback
        "::1",  # loopback (v6)
        "10.0.0.1",  # private
        "172.16.0.1",  # private
        "192.168.1.1",  # private
        "169.254.169.254",  # link-local / cloud metadata endpoint
        "169.254.0.1",  # link-local
        "0.0.0.0",  # unspecified
        "224.0.0.1",  # multicast
    ],
)
def test_is_safe_ip_rejects_dangerous_addresses(ip_str: str) -> None:
    assert is_safe_ip(ip_str) is False


@pytest.mark.parametrize("ip_str", ["8.8.8.8", "1.1.1.1", "93.184.216.34"])
def test_is_safe_ip_accepts_public_addresses(ip_str: str) -> None:
    assert is_safe_ip(ip_str) is True


def test_is_safe_ip_rejects_garbage_input() -> None:
    assert is_safe_ip("not-an-ip-address") is False


# --- validate_target_url: scheme + resolution + policy, end to end ---


def test_rejects_disallowed_scheme() -> None:
    with pytest.raises(UnsafeURLError):
        validate_target_url("ftp://example.com/file")


def test_rejects_file_scheme() -> None:
    with pytest.raises(UnsafeURLError):
        validate_target_url("file:///etc/passwd")


def test_rejects_url_with_no_hostname() -> None:
    with pytest.raises(UnsafeURLError):
        validate_target_url("http:///path-only")


def test_accepts_literal_public_ip_no_resolver_needed() -> None:
    # No resolver passed at all — proves literal IPs never hit DNS.
    assert validate_target_url("http://93.184.216.34/") == "http://93.184.216.34/"


def test_rejects_literal_loopback_ip() -> None:
    with pytest.raises(UnsafeURLError):
        validate_target_url("http://127.0.0.1/admin")


def test_rejects_literal_cloud_metadata_ip() -> None:
    with pytest.raises(UnsafeURLError):
        validate_target_url("http://169.254.169.254/latest/meta-data/")


def test_rejects_hostname_resolving_to_private_ip() -> None:
    resolver = _fake_resolver("internal.example.test", ["10.0.0.5"])
    with pytest.raises(UnsafeURLError):
        validate_target_url("http://internal.example.test/", resolver=resolver)


def test_accepts_hostname_resolving_to_public_ip() -> None:
    resolver = _fake_resolver("public.example.test", ["93.184.216.34"])
    assert validate_target_url("https://public.example.test/page", resolver=resolver) == (
        "https://public.example.test/page"
    )


def test_rejects_hostname_with_no_resolved_addresses() -> None:
    resolver = _fake_resolver("nowhere.example.test", [])
    with pytest.raises(UnsafeURLError):
        validate_target_url("http://nowhere.example.test/", resolver=resolver)


def test_rejects_hostname_if_any_resolved_address_is_unsafe() -> None:
    # Multiple A records, one of which is dangerous — must fail closed.
    resolver = _fake_resolver("mixed.example.test", ["93.184.216.34", "127.0.0.1"])
    with pytest.raises(UnsafeURLError):
        validate_target_url("http://mixed.example.test/", resolver=resolver)
