"""Track owner-notified quality count.

Revision ID: 20260920_0003
Revises: 20260920_0002
Create Date: 2026-09-20
"""

import sqlalchemy as sa
from alembic import op

revision = "20260920_0003"
down_revision = "20260920_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "movies",
        sa.Column(
            "owner_notification_quality_count",
            sa.SmallInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_movies_owner_notification_quality_count",
        "movies",
        "owner_notification_quality_count >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_movies_owner_notification_quality_count",
        "movies",
        type_="check",
    )
    op.drop_column("movies", "owner_notification_quality_count")
