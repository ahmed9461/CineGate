"""Add durable historical archive import state.

Revision ID: 20260920_0010
Revises: 20260920_0009
Create Date: 2026-09-20
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260920_0010"
down_revision = "20260920_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "archive_import_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_channel_id", sa.BigInteger(), nullable=False),
        sa.Column("archive_channel_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("source_high_watermark_id", sa.BigInteger(), nullable=True),
        sa.Column("archive_baseline_message_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "last_copied_source_message_id",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "last_reindexed_source_message_id",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("source_total_estimate", sa.BigInteger(), nullable=True),
        sa.Column(
            "processed_messages",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "copied_messages",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "reconciled_messages",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "skipped_messages",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "reindexed_messages",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "missing_archive_messages",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("owner_progress_message_id", sa.BigInteger(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ("
            "'ready', 'running', 'paused', 'transferred', "
            "'reindexing', 'completed', 'failed'"
            ")",
            name="ck_archive_import_jobs_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_channel_id",
            "archive_channel_id",
            name="uq_archive_import_jobs_source_archive",
        ),
    )
    op.create_index(
        "ix_archive_import_jobs_archive_status",
        "archive_import_jobs",
        ["archive_channel_id", "status"],
        unique=False,
    )

    op.create_table(
        "archive_import_message_map",
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_message_id", sa.BigInteger(), nullable=False),
        sa.Column("archive_message_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "copied_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("reindexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["archive_import_jobs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("job_id", "source_message_id"),
        sa.UniqueConstraint(
            "job_id",
            "archive_message_id",
            name="uq_archive_import_map_job_archive_message",
        ),
    )
    op.create_index(
        "ix_archive_import_map_job_source",
        "archive_import_message_map",
        ["job_id", "source_message_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_archive_import_map_job_source",
        table_name="archive_import_message_map",
    )
    op.drop_table("archive_import_message_map")
    op.drop_index(
        "ix_archive_import_jobs_archive_status",
        table_name="archive_import_jobs",
    )
    op.drop_table("archive_import_jobs")
