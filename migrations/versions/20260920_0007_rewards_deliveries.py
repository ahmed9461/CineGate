"""Add reward sessions and durable deliveries.

Revision ID: 20260920_0007
Revises: 20260920_0006
Create Date: 2026-09-20
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260920_0007"
down_revision = "20260920_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reward_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("movie_id", sa.BigInteger(), nullable=False),
        sa.Column("movie_quality_id", sa.BigInteger(), nullable=False),
        sa.Column("quality", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("prompt_message_id", sa.BigInteger(), nullable=True),
        sa.Column("prompt_claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("client_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rewarded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivery_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ("
            "'pending', 'client_completed', 'provider_confirmed', "
            "'rewarded', 'delivering', 'delivered', 'expired'"
            ")",
            name="ck_reward_sessions_status",
        ),
        sa.ForeignKeyConstraint(["movie_id"], ["movies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["movie_quality_id"],
            ["movie_qualities.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_reward_sessions_active_user",
        "reward_sessions",
        ["telegram_user_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ("
            "'pending', 'client_completed', 'provider_confirmed', "
            "'rewarded', 'delivering'"
            ")"
        ),
    )
    op.create_index(
        "ix_reward_sessions_user_created",
        "reward_sessions",
        ["telegram_user_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "deliveries",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("reward_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("movie_quality_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=True),
        sa.Column("send_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delete_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delete_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "attempts",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'sending', 'sent', 'deleting', 'deleted')",
            name="ck_deliveries_status",
        ),
        sa.ForeignKeyConstraint(
            ["movie_quality_id"],
            ["movie_qualities.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reward_session_id"],
            ["reward_sessions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "reward_session_id",
            name="uq_deliveries_reward_session",
        ),
    )
    op.create_index(
        "ix_deliveries_due",
        "deliveries",
        ["status", "next_attempt_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_deliveries_due", table_name="deliveries")
    op.drop_table("deliveries")
    op.drop_index("ix_reward_sessions_user_created", table_name="reward_sessions")
    op.drop_index("uq_reward_sessions_active_user", table_name="reward_sessions")
    op.drop_table("reward_sessions")
