"""Add owner notification message reference.

Revision ID: 20260920_0002
Revises: 20260920_0001
Create Date: 2026-09-20
"""

import sqlalchemy as sa
from alembic import op

revision = "20260920_0002"
down_revision = "20260920_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "movies",
        sa.Column("owner_notification_message_id", sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("movies", "owner_notification_message_id")
