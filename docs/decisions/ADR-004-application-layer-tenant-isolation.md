# ADR-004: Application-Layer Tenant Isolation over PostgreSQL RLS

## Context

Section 13 requires that tenant-scoped resources never leak across
organizations, and that `organization_id` supplied by the client is
never trusted for authorization. PostgreSQL Row-Level Security (RLS)
is one way to enforce this at the database layer; application-layer
checks are another.

## Decision

Phase 1 enforces tenant isolation entirely at the application layer:
every protected route depends on `require_membership`
(`apps/api/app/api/deps.py`), which derives `organization_id` from a
verified DB lookup of (authenticated user, claimed org), never from
the request. **PostgreSQL RLS is explicitly NOT implemented in
Phase 1** — this was an explicit instruction in the Phase 1 approval,
not a default assumption, and must not be silently added later
without a new approved decision.

## Reasoning

- Section 1.6 (no unjustified complexity): RLS requires
  `SET LOCAL`/`set_config` session variables wired through every
  connection, careful handling of connection pooling (a pooled
  connection must have its RLS context reset between uses or it
  leaks between requests), and policies defined per table — real
  engineering cost with no corresponding Phase 1 requirement that
  application-layer checks can't satisfy.
- Phase 1's own acceptance criterion is behavioral ("cross-tenant
  access tests must fail correctly"), not "RLS must exist" —
  satisfiable and tested at the application layer (see
  `apps/api/tests/integration/test_auth_flow.py`,
  `test_cross_tenant_access_is_denied` and
  `test_idor_non_member_cannot_access_any_organization`).

## Security implications

Application-layer isolation is only as strong as EVERY code path
that touches tenant data. A future service function that queries
`organizations`/`organization_members`-adjacent tables without going
through `require_membership` (or equivalent) would reintroduce a
cross-tenant leak that RLS would have caught even from a buggy query.
This is a real, accepted risk in Phase 1 — mitigated by:
- One reusable dependency (`require_membership`) rather than
  ad-hoc checks copy-pasted per route.
- Cross-tenant/IDOR tests are mandatory per-route going forward, not
  optional.

## Testing strategy

Every new tenant-scoped route added in future phases must include an
explicit cross-tenant access test (User A cannot touch Org B's
resource) as part of its own Definition of Done — this is now the
standing pattern established by Phase 1, not a one-time check.

## When to revisit RLS

Re-evaluate as a new ADR if any of these occur:
- A second application-layer bug ships to production that leaks
  data across tenants (one incident is a bug to fix; a second
  suggests the layer itself is insufficient).
- Compliance requirements (e.g. an enterprise customer's security
  review, SOC 2 audit) specifically require database-enforced
  tenant isolation as defense-in-depth.
- The number of tenant-scoped tables/query paths grows large enough
  that auditing "did every path go through require_membership"
  manually becomes unreliable.
