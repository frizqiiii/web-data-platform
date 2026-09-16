"""phase0 baseline: prove the migration pipeline works end-to-end

Revision ID: 0001
Revises:
Create Date: 2026-09-17

Phase 0 scope ONLY. This migration creates a single marker table
with no domain meaning. Its sole purpose is to prove that
`alembic upgrade head` and `alembic downgrade -1` both work against a
real PostgreSQL instance — one of the Phase 0 acceptance criteria.

Domain tables (organizations, users, projects, ...) are introduced
starting Phase 1, each as its own reviewed migration. This baseline
table (_phase0_baseline) should be dropped by a Phase 1 migration
once real tables exist, rather than left around indefinitely —
noting that here so it isn't forgotten or mistaken for a real table.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "_phase0_baseline",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("_phase0_baseline")
