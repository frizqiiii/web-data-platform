"""Compatibility re-export shim (Phase 3, ADR-006/ADR-009 Decision #1).

The real implementation moved to `packages/security/url_safety.py` so
apps/worker can share the exact same SSRF-validation logic instead of
a second, independently-maintained copy. This module exists only so
existing imports elsewhere in apps/api —

    from app.core.url_safety import validate_target_url
    from app.core.url_safety import UnsafeURLError

(see app/services/target_service.py, app/modules/targets/router.py,
app/models/target.py) — keep working completely unchanged. Do not add
new logic here; add it to packages/security/url_safety.py instead.
"""

from packages.security.url_safety import (
    ALLOWED_SCHEMES,
    HostnameResolver,
    PinnedTarget,
    SystemResolver,
    UnsafeURLError,
    is_safe_ip,
    resolve_and_pin,
    validate_target_url,
)

__all__ = [
    "ALLOWED_SCHEMES",
    "HostnameResolver",
    "PinnedTarget",
    "SystemResolver",
    "UnsafeURLError",
    "is_safe_ip",
    "resolve_and_pin",
    "validate_target_url",
]
