"""Add durable user search session.

Revision ID: 20260920_0005
Revises: 20260920_0004
Create Date: 2026-09-20
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260920_0005"
down_revision = "20260920_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_search_sessions",
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("nonce", sa.String(length=16), nullable=False),
        sa.Column("raw_query", sa.String(length=128), nullable=False),
        sa.Column("normalized_query", sa.String(length=512), nullable=False),
        sa.Column(
            "result_movie_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("selected_movie_id", sa.BigInteger(), nullable=True),
        sa.Column("result_message_id", sa.BigInteger(), nullable=True),
        sa.Column("poster_message_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "state IN ('results', 'opening', 'movie', 'returning')",
            name="ck_user_search_sessions_state",
        ),
        sa.ForeignKeyConstraint(
            ["selected_movie_id"],
            ["movies.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("telegram_user_id"),
    )


def downgrade() -> None:
    op.drop_table("user_search_sessions")
