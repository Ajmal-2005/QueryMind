"""phase 5: corrections and glossary

Revision ID: e7b2f1c85a40
Revises: c4e1a90f7b23
Create Date: 2026-08-16 14:05:00.000000
"""

from collections.abc import Sequence

# The embedding column renders as a pgvector type under the postgresql
# variant, so the module must be importable when this migration runs.
import pgvector.sqlalchemy  # noqa: F401
import sqlalchemy as sa

from alembic import op
from app.models.schema_index import EMBEDDING_DIM

revision: str = "e7b2f1c85a40"
down_revision: str | None = "c4e1a90f7b23"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _embedding() -> sa.types.TypeEngine:
    from pgvector.sqlalchemy import Vector

    return sa.JSON().with_variant(Vector(EMBEDDING_DIM), "postgresql")


def upgrade() -> None:
    op.create_table(
        "corrections",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("query_id", sa.String(length=36), nullable=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("connection_id", sa.String(length=36), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("original_sql", sa.Text(), nullable=True),
        sa.Column("corrected_sql", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("embedding", _embedding(), nullable=True),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column("times_used", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["query_id"], ["queries.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["connections.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_corrections_user_id", "corrections", ["user_id"])
    op.create_index("ix_corrections_connection_id", "corrections", ["connection_id"])
    op.create_index("ix_corrections_created_at", "corrections", ["created_at"])

    op.create_table(
        "glossary_terms",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("connection_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("term", sa.String(length=200), nullable=False),
        sa.Column("definition", sa.Text(), nullable=False),
        sa.Column("sql_expression", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["connections.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        # One agreed definition per term per database.
        sa.UniqueConstraint(
            "connection_id", "term", name="uq_glossary_connection_term"
        ),
    )
    op.create_index(
        "ix_glossary_terms_connection_id", "glossary_terms", ["connection_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_glossary_terms_connection_id", table_name="glossary_terms")
    op.drop_table("glossary_terms")
    op.drop_index("ix_corrections_created_at", table_name="corrections")
    op.drop_index("ix_corrections_connection_id", table_name="corrections")
    op.drop_index("ix_corrections_user_id", table_name="corrections")
    op.drop_table("corrections")
