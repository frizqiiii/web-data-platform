"""CSRF protection for cookie-based browser sessions (Decision C).

Design: server-verified double-submit. At login, a CSRF token is
generated and stored INSIDE the session's Redis record (not derivable
from the session token itself), then set as a non-httpOnly cookie so
browser JS can read it and echo it back as a request header on every
state-changing request. The server compares the header value against
the one stored server-side for that session — NOT just "cookie value
equals header value" (a pure double-submit), which is weaker on its
own. CORS is NOT a substitute for this (Decision C) — CORS controls
which origins can read a response, not which origins can cause a
same-site browser to send a cookie-bearing request in the first
place.

Bearer-token API consumers (non-browser) are exempt: CSRF is a
browser/cookie-specific threat, since Bearer tokens are never sent
automatically by a browser the way cookies are.
"""

from app.core.security import generate_token

CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"


def generate_csrf_token() -> str:
    return generate_token()


def csrf_token_matches(cookie_value: str | None, header_value: str | None) -> bool:
    """Both must be present and equal. Comparison happens against the
    session-stored value by the caller (app/api/deps.py) — this
    function only checks the request-side pair is well-formed and
    consistent, not that it matches the session record."""
    if not cookie_value or not header_value:
        return False
    return cookie_value == header_value
