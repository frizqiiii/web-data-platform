"""SSRF-safe URL validation and DNS-rebinding-safe IP pinning.

This is the SINGLE shared implementation used by both apps/api (Phase
2: creation-time Target URL validation) and apps/worker (Phase 3:
execution-time re-validation + IP pinning). There must never be a
second, independently-maintained copy of this logic — see ADR-006
and ADR-009.

`apps/api/app/core/url_safety.py` is a thin compatibility re-export
of this module (existing API imports like `from
app.core.url_safety import validate_target_url` keep working
unchanged). `apps/worker` imports from here directly, since it has no
equivalent legacy module to stay compatible with.

Phase 2 scope (`validate_target_url`): validate at Target
create/update time — block dangerous schemes and obvious
private/loopback/link-local/metadata addresses. This is NOT
sufficient on its own for actual fetching: a URL safe at creation is
not guaranteed safe at execution time (DNS can change in between —
DNS rebinding). That is what Phase 3's `resolve_and_pin` closes: it
resolves DNS exactly once, validates every candidate IP, and returns
a single validated IP an HTTP client can connect to *directly* —
instead of connecting via the hostname a second time, which would
reopen the same TOCTOU window this module exists to close.

The resolver is injectable specifically so unit tests can exercise
the blocking logic deterministically without real DNS/network calls
(see apps/api/tests/unit/test_url_safety.py and
apps/worker/tests/test_url_safety_shared.py) — the default
`SystemResolver` is what's actually used in the running application.
"""

import ipaddress
import socket
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import ParseResult, urlparse

ALLOWED_SCHEMES = {"http", "https"}

_DEFAULT_PORTS = {"http": 80, "https": 443}


class UnsafeURLError(ValueError):
    """Raised for any URL that is malformed, uses a disallowed
    scheme, or resolves to a disallowed address. Deliberately a single
    exception type — callers (API validators, execution engines)
    don't need to distinguish why a URL was rejected, only that it
    was."""


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


def _resolve_candidate_ips(hostname: str, resolver: HostnameResolver | None) -> list[str]:
    """Literal IP hostnames never hit DNS or the injected resolver —
    this is also what lets tests exercise the "blocked" path (e.g. a
    169.254.169.254 literal) with zero network dependency."""
    try:
        literal_ip = ipaddress.ip_address(hostname)
        return [str(literal_ip)]
    except ValueError:
        active_resolver = resolver or SystemResolver()
        return active_resolver.resolve(hostname)


def validate_target_url(url: str, resolver: HostnameResolver | None = None) -> str:
    """Validates `url` is a plausible, non-obviously-dangerous
    scraping target. Returns the URL unchanged if it passes (so this
    can be used directly as a pydantic validator return value).
    Raises UnsafeURLError otherwise.

    Phase 2 creation-time check only. Does not pin an IP — a
    hostname's DNS can change between this call and when Phase 3
    actually fetches the URL. Use `resolve_and_pin` at execution time
    instead of trusting that a URL which passed this check earlier is
    still safe now.
    """
    parsed = _parse_and_check_scheme(url)
    hostname = parsed.hostname
    assert hostname is not None  # guaranteed by _parse_and_check_scheme

    candidate_ips = _resolve_candidate_ips(hostname, resolver)

    if not candidate_ips:
        raise UnsafeURLError(f"hostname resolved to no addresses: {hostname}")

    for ip_str in candidate_ips:
        if not is_safe_ip(ip_str):
            raise UnsafeURLError(f"URL resolves to a disallowed address: {ip_str}")

    return url


@dataclass(frozen=True)
class PinnedTarget:
    """The result of `resolve_and_pin`: a single DNS resolution,
    fully validated, ready for a connection to be made to the exact
    IP that was checked — closing the DNS-rebinding TOCTOU window
    (ADR-009).

    `hostname` (never `pinned_ip`) is what callers must still put in
    the Host header and use for TLS SNI/certificate verification —
    pinning the connection to an IP must not also mean connecting
    "as" that IP; the request must remain indistinguishable, from the
    origin server's point of view, from a normal request to
    `hostname`.
    """

    scheme: str
    hostname: str
    port: int
    pinned_ip: str
    url: str


def resolve_and_pin(url: str, resolver: HostnameResolver | None = None) -> PinnedTarget:
    """Resolve `url`'s hostname exactly once, validate every
    candidate address, and return one validated IP to connect to
    directly.

    This is the execution-time counterpart to `validate_target_url`.
    The critical difference is the *shape* of the result: callers
    must connect to `PinnedTarget.pinned_ip` directly rather than
    resolving `hostname` a second time through a normal HTTP client —
    a second resolution is exactly the gap that lets DNS rebinding
    defeat a "validate, then connect by hostname" pipeline (resolve
    #1 returns a public IP that passes validation, resolve #2 — done
    by the HTTP client's own connect step — returns a private IP,
    because the attacker's DNS server changed its answer in between).

    Fails closed: if any resolved address is unsafe, the whole
    lookup is rejected (same policy as `validate_target_url`) even
    though only one IP is ultimately used — a hostname that
    round-robins between a safe and an unsafe address is not a
    hostname this platform should ever connect to, regardless of
    which answer happens to come back first.
    """
    parsed = _parse_and_check_scheme(url)
    hostname = parsed.hostname
    assert hostname is not None  # guaranteed by _parse_and_check_scheme

    candidate_ips = _resolve_candidate_ips(hostname, resolver)

    if not candidate_ips:
        raise UnsafeURLError(f"hostname resolved to no addresses: {hostname}")

    for ip_str in candidate_ips:
        if not is_safe_ip(ip_str):
            raise UnsafeURLError(f"URL resolves to a disallowed address: {ip_str}")

    port = parsed.port or _DEFAULT_PORTS[parsed.scheme]

    return PinnedTarget(
        scheme=parsed.scheme,
        hostname=hostname,
        port=port,
        pinned_ip=candidate_ips[0],
        url=url,
    )
