# ADR-009: DNS-Rebinding Mitigation via IP-Pinning

## Context

ADR-006 (Phase 2) established creation-time SSRF validation for
`Target.url`: on create/update, the hostname is resolved and every
resolved address is checked against `is_safe_ip` (blocking
loopback/private/link-local/metadata/multicast/reserved/unspecified
ranges). ADR-006 explicitly flagged, at the time, that this is not
sufficient for the moment of actual fetching:

> Phase 3 (execution) MUST re-validate immediately before every
> request AND on every redirect hop — a URL safe at Target-creation
> time is not guaranteed safe at execution time.

The reason a second, execution-time check is necessary — and not
merely "extra caution" — is DNS rebinding: an attacker controlling
the DNS answer for a hostname can return a public (safe) IP the first
time it's resolved, and a private/internal (unsafe) IP the next time.
If Phase 3's execution pipeline were:

```
resolve hostname → validate the IP → connect using the hostname
```

the connect step's own DNS resolution is a **second** lookup — and by
design it happens after validation, at a time an attacker fully
controls. A rebinding attacker only needs the validation lookup to
return something safe and the connect lookup to return something
unsafe; nothing about "validate first" prevents that, because
validating and connecting are two separate resolutions of the same
attacker-controlled name.

## Decision

Full IP-pinning. `packages/security/url_safety.py`'s `resolve_and_pin`
resolves a hostname **exactly once**, validates every candidate
address from that single resolution, and returns a `PinnedTarget`
carrying the one validated IP the HTTP engine must connect to
**directly** — never by asking anything (the OS resolver, httpx,
httpcore) to resolve the hostname again.

```
URL
 → parse
 → resolve once
 → validate every resolved IP
 → choose the first validated IP
 → connect directly to that IP
 → Host header = original hostname
 → TLS SNI / certificate verification = original hostname
```

Concretely, in `worker/engines/http/engine.py`, the outgoing request
is built with `httpx.URL(host=pinned.pinned_ip, ...)` — so the
connection layer never re-resolves — while `Host: {pinned.hostname}`
is set explicitly and the `sni_hostname` request extension is set to
`pinned.hostname` for HTTPS requests, so the TLS handshake's SNI and
the certificate hostname check both still validate against the real
hostname, not the IP. TLS verification (`verify=True`) is never
disabled to make this work.

This re-validation happens **on every redirect hop independently** —
a redirect target is a new hostname (or the same one, re-resolved),
and gets its own `resolve_and_pin` call, its own fresh single
resolution, and its own pinned connection. Nothing about following a
redirect trusts an earlier hop's validation.

## Reasoning

- **"Resolve, validate, connect-by-hostname" only looks safe.** It
  reintroduces exactly the TOCTOU (time-of-check to time-of-use)
  window the validation step exists to close, because "connect by
  hostname" silently means "resolve again, elsewhere, later, without
  validation." Pinning removes the second resolution entirely rather
  than trying to make it safe.
- **The hostname must still be presented, not the IP.** Connecting to
  an IP while sending `Host: <IP>` (or letting TLS SNI default to the
  IP) would change what server-side virtual-hosting and certificate
  matching see — the origin server would likely reject or
  misroute the request, and for TLS, an IP-based SNI/cert check would
  fail against a cert issued for the hostname. Explicitly forcing
  `Host` and `sni_hostname` to the original hostname keeps the
  request indistinguishable, from the target server's perspective,
  from a normal request to that hostname — the only thing that
  changed is which network layer decided the destination IP.
- **Fail-closed on any unsafe candidate, not just the one chosen.**
  `resolve_and_pin` rejects the whole lookup if *any* resolved address
  is unsafe, even though only one IP is ultimately connected to. A
  hostname that round-robins between a safe and an unsafe address is
  not a hostname this platform should trust at all, regardless of
  which answer happens to be picked.
- **No connection-pool reuse across hostnames/hops.** The HTTP
  engine's client is built with `max_keepalive_connections=0` (see
  the engine module's docstring for the full trade-off) specifically
  so a connection whose identity is tied to one validated pinned IP
  can never be silently reused for a different hostname's request —
  reusing pooled connections keyed loosely could otherwise undermine
  the guarantee that every hop's IP was independently validated.

## Known limitation

The `sni_hostname` extension mechanism this ADR relies on is
httpx/httpcore's documented approach for exactly this "pin the
connection, present a different hostname" scenario, but **could not
be exercised against a real TLS connection in the environment this
was authored in** (no network access to install `httpx` at all — see
PHASE_3_REPORT.md). This is recorded as `UNVERIFIED`, not `PASS`,
until CI (which has network) runs `apps/worker/tests/engines/http/`.
