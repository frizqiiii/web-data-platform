"""SSRF-safe URL validation (Decision #4, ADR-006).

Scope for Phase 2 (per explicit approval): validate at Target
create/update time — block dangerous schemes and obvious private/
loopback/link-local/metadata addresses. This is NOT sufficient on its
own for actual fetching: Phase 3's engines MUST re-validate
immediately before every request AND on every redirect hop, and must
not trust that a URL passing this check is still safe later (DNS
rebinding, TOCTOU). That is a recorded Phase 3 dependency, not
something this module can guarantee.

The resolver is injectable specifically so unit tests can exercise
the blocking logic deterministically without real DNS/network calls
(see apps/api/tests/unit/test_url_safety.py) — the default
`SystemResolver` is what's actually used in the running application.
"""

import ipaddress
import socket
from typing import Protocol
from urllib.parse import ParseResult, urlparse

ALLOWED_SCHEMES = {"http", "https"}


class UnsafeURLError(ValueError):
    """Raised for any URL that is malformed, uses a disallowed
    scheme, or resolves to a disallowed address. Deliberately a single
    exception type — callers (API validators) don't need to
    distinguish why a URL was rejected, only that it was."""


class HostnameResolver(Protocol):
    def resolve(self, hostname: str) -> list[str]: ...


class SystemResolver:
    """Real DNS resolution via the OS resolver. Used by default in
    the running application; NOT used in unit tests."""

    def resolve(self, hostname: str) -> list[str]:
        try:
            infos = socket.getaddrinfo(hostname, None)
        except socket.gaierror as exc:
            raise UnsafeURLError(f"could not resolve hostname: {hostname}") from exc
        # info[4] is a sockaddr tuple (str, int) for IPv4 or
        # (str, int, int, int) for IPv6 — index [0] is the address in
        # both, but mypy's typeshed stub widens it to str | int across
        # the union (found by actually running mypy); str(...) makes
        # the actual (already-string) value explicit rather than
        # papering over it with a cast.
        return [str(info[4][0]) for info in infos]


def is_safe_ip(ip_str: str) -> bool:
    """True if this address is a normal, routable, public unicast
    address — false for anything in a range that should never be a
    legitimate scraping target (loopback, private LAN, link-local
    including the 169.254.169.254 cloud metadata endpoint, multicast,
    reserved, or unspecified)."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _parse_and_check_scheme(url: str) -> ParseResult:
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise UnsafeURLError(f"disallowed URL scheme: {parsed.scheme!r}")
    if not parsed.hostname:
        raise UnsafeURLError("URL has no hostname")
    return parsed


def validate_target_url(url: str, resolver: HostnameResolver | None = None) -> str:
    """Validates `url` is a plausible, non-obviously-dangerous
    scraping target. Returns the URL unchanged if it passes (so this
    can be used directly as a pydantic validator return value).
    Raises UnsafeURLError otherwise.

    If the hostname is already a literal IP address, no DNS
    resolution happens at all — the literal is checked directly. This
    is also why a test can exercise the "blocked" path (e.g. a
    169.254.169.254 literal) with zero network dependency.
    """
    parsed = _parse_and_check_scheme(url)
    hostname = parsed.hostname
    assert hostname is not None  # guaranteed by _parse_and_check_scheme

    try:
        literal_ip = ipaddress.ip_address(hostname)
        candidate_ips = [str(literal_ip)]
    except ValueError:
        active_resolver = resolver or SystemResolver()
        candidate_ips = active_resolver.resolve(hostname)

    if not candidate_ips:
        raise UnsafeURLError(f"hostname resolved to no addresses: {hostname}")

    for ip_str in candidate_ips:
        if not is_safe_ip(ip_str):
            raise UnsafeURLError(f"URL resolves to a disallowed address: {ip_str}")

    return url
