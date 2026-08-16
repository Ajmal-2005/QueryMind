"""phase 4: dashboards and tiles

Revision ID: c4e1a90f7b23
Revises: 06416bc9097c
Create Date: 2026-08-16 11:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c4e1a90f7b23"
down_revision: str | None = "06416bc9097c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dashboards",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("layout", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dashboards_user_id", "dashboards", ["user_id"])

    op.create_table(
        "dashboard_tiles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("dashboard_id", sa.String(length=36), nullable=False),
        sa.Column("connection_id", sa.String(length=36), nullable=True),
        sa.Column("query_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("question", sa.Text(), nullable=True),
        sa.Column("sql", sa.Text(), nullable=False),
        sa.Column("chart", sa.JSON(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["dashboard_id"], ["dashboards.id"], ondelete="CASCADE"
        ),
        # A deleted connection leaves the tile in place, reporting that its
        # database is gone — quieter than a dashboard that loses tiles.
        sa.ForeignKeyConstraint(
            ["connection_id"], ["connections.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["query_id"], ["queries.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_dashboard_tiles_dashboard_id", "dashboard_tiles", ["dashboard_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_dashboard_tiles_dashboard_id", table_name="dashboard_tiles")
    op.drop_table("dashboard_tiles")
    op.drop_index("ix_dashboards_user_id", table_name="dashboards")
    op.drop_table("dashboards")
