"""phase2: projects, scrapers, targets

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-19

Per approved Migration Policy: 0001 and 0002 are NOT modified. This
migration only adds new tables on top of them.

Status columns use String + CheckConstraint (Decision #3), not a
native PostgreSQL ENUM — kept in sync BY HAND with the StrEnum
classes in app/models/{project,scraper}.py (ProjectStatus,
ScraperStatus, ScraperEngine). Any future status/engine value change
requires updating both the Python enum AND this migration's
CheckConstraint together — there is no automatic sync mechanism.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- projects ---
    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="DRAFT"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "status IN ('DRAFT','ACTIVE','PAUSED','ARCHIVED')", name="ck_projects_status"
        ),
    )
    op.create_unique_constraint("uq_project_org_slug", "projects", ["organization_id", "slug"])
    op.create_index("ix_projects_organization_id", "projects", ["organization_id"])
    op.create_index("ix_projects_status", "projects", ["status"])

    # --- scrapers ---
    op.create_table(
        "scrapers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("engine", sa.String(length=20), nullable=False),
        sa.Column(
            "configuration",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("credential_reference", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="DRAFT"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint("engine IN ('HTTP','BROWSER','SCRAPY')", name="ck_scrapers_engine"),
        sa.CheckConstraint(
            "status IN ('DRAFT','ACTIVE','DISABLED','ARCHIVED')", name="ck_scrapers_status"
        ),
    )
    op.create_unique_constraint("uq_scraper_project_slug", "scrapers", ["project_id", "slug"])
    op.create_index("ix_scrapers_project_id", "scrapers", ["project_id"])
    op.create_index("ix_scrapers_status", "scrapers", ["status"])

    # --- targets ---
    op.create_table(
        "targets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("scraper_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["scraper_id"], ["scrapers.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_targets_scraper_id", "targets", ["scraper_id"])


def downgrade() -> None:
    op.drop_index("ix_targets_scraper_id", table_name="targets")
    op.drop_table("targets")

    op.drop_index("ix_scrapers_status", table_name="scrapers")
    op.drop_index("ix_scrapers_project_id", table_name="scrapers")
    op.drop_table("scrapers")

    op.drop_index("ix_projects_status", table_name="projects")
    op.drop_index("ix_projects_organization_id", table_name="projects")
    op.drop_table("projects")
