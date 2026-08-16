"""phase 7: store the resolved question on each query

Revision ID: b91d3c07f4e8
Revises: e7b2f1c85a40
Create Date: 2026-08-16 23:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b91d3c07f4e8"
down_revision: str | None = "e7b2f1c85a40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable, with no backfill: rows written before this column existed have
    # no resolved text to recover, and `_recent_questions` falls back to the
    # raw question for them.
    op.add_column("queries", sa.Column("resolved_question", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("queries", "resolved_question")
