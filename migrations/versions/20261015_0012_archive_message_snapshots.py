"""Persist Archive stream boundaries and edit freshness.

Revision ID: 20261015_0012
Revises: 20261015_0011
"""

import sqlalchemy as sa
from alembic import op

revision = "20261015_0012"
down_revision = "20261015_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "archive_message_snapshots",
        sa.Column("archive_channel_id", sa.BigInteger(), primary_key=True),
        sa.Column("message_id", sa.BigInteger(), primary_key=True),
        sa.Column("media_kind", sa.String(16), nullable=False),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("conflicted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.CheckConstraint(
            "media_kind IN ('photo', 'video', 'document', 'other')",
            name="ck_archive_message_snapshots_media_kind",
        ),
    )
    # Preserve existing invalidations as well as valid captions. Older ignored
    # stream events are unknowable until the operator runs a full history replay.
    op.execute(
        "INSERT INTO archive_message_snapshots "
        "(archive_channel_id, message_id, media_kind, caption) "
        "SELECT archive_channel_id, poster_message_id, "
        "CASE WHEN parser_confidence > 0 THEN 'photo' ELSE 'other' END, raw_poster_caption "
        "FROM movies ON CONFLICT DO NOTHING"
    )
    op.execute(
        "INSERT INTO archive_message_snapshots "
        "(archive_channel_id, message_id, media_kind, caption) "
        "SELECT archive_channel_id, archive_message_id, "
        "CASE WHEN parser_confidence > 0 THEN 'video' ELSE 'other' END, raw_caption "
        "FROM movie_qualities ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    # Index rows/earned entitlements stay intact. Downgrade loses replay/version
    # evidence and requires a full reindex on a subsequent upgrade.
    op.drop_table("archive_message_snapshots")
