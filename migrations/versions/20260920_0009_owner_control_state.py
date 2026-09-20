"""Add owner edit sessions and admin audit log.

Revision ID: 20260920_0009
Revises: 20260920_0008
Create Date: 2026-09-20
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260920_0009"
down_revision = "20260920_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "owner_edit_sessions",
        sa.Column("owner_user_id", sa.BigInteger(), nullable=False),
        sa.Column("edit_kind", sa.String(length=16), nullable=False),
        sa.Column("target_key", sa.String(length=128), nullable=False),
        sa.Column(
            "started_at",
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
            "edit_kind IN ('setting', 'template')",
            name="ck_owner_edit_sessions_kind",
        ),
        sa.PrimaryKeyConstraint("owner_user_id"),
    )

    op.create_table(
        "admin_audit_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("owner_user_id", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("target_type", sa.String(length=16), nullable=False),
        sa.Column("target_key", sa.String(length=128), nullable=False),
        sa.Column(
            "old_value",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "new_value",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "target_type IN ('setting', 'template')",
            name="ck_admin_audit_log_target_type",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_admin_audit_log_owner_created",
        "admin_audit_log",
        ["owner_user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_admin_audit_log_owner_created",
        table_name="admin_audit_log",
    )
    op.drop_table("admin_audit_log")
    op.drop_table("owner_edit_sessions")
