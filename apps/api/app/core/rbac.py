"""Explicit RBAC role hierarchy (Decision E).

RULE: role comparison is NEVER done by alphabetical/string ordering
— that's coincidental and would silently break the moment role names
change. This is the single source of truth for "is role X allowed to
do something that requires at least role Y".
"""

from app.models.organization_member import OrgRole

# Explicit, ordered mapping — higher number = more privilege.
# Section E: OWNER > ADMIN > MANAGER > OPERATOR > ANALYST > VIEWER.
ROLE_RANK: dict[str, int] = {
    OrgRole.VIEWER.value: 1,
    OrgRole.ANALYST.value: 2,
    OrgRole.OPERATOR.value: 3,
    OrgRole.MANAGER.value: 4,
    OrgRole.ADMIN.value: 5,
    OrgRole.OWNER.value: 6,
}


def role_satisfies(actual_role: str, required_role: str) -> bool:
    """True if `actual_role` has at least the privilege of `required_role`."""
    return ROLE_RANK.get(actual_role, 0) >= ROLE_RANK.get(required_role, 0)
