"""Unit tests for the explicit role hierarchy (Decision E).

Specifically guards against ever reverting to alphabetical/string
comparison, which would silently break (e.g. "ADMIN" < "OWNER"
alphabetically is true, which is coincidentally correct, but
"ANALYST" < "VIEWER" alphabetically is also true, which is WRONG —
ANALYST must outrank VIEWER)."""

from app.core.rbac import role_satisfies


def test_owner_satisfies_every_lower_role() -> None:
    for required in ["OWNER", "ADMIN", "MANAGER", "OPERATOR", "ANALYST", "VIEWER"]:
        assert role_satisfies("OWNER", required) is True


def test_viewer_only_satisfies_viewer() -> None:
    assert role_satisfies("VIEWER", "VIEWER") is True
    for required in ["OWNER", "ADMIN", "MANAGER", "OPERATOR", "ANALYST"]:
        assert role_satisfies("VIEWER", required) is False


def test_analyst_outranks_viewer_despite_alphabetical_order() -> None:
    """Regression guard: 'ANALYST' < 'VIEWER' alphabetically, but
    ANALYST is a higher role — this must not be checked by string
    comparison."""
    assert role_satisfies("ANALYST", "VIEWER") is True
    assert role_satisfies("VIEWER", "ANALYST") is False


def test_unknown_role_satisfies_nothing() -> None:
    assert role_satisfies("NOT_A_REAL_ROLE", "VIEWER") is False
