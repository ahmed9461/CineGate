"""Index quality-caption titles as search aliases.

Revision ID: 20260920_0006
Revises: 20260920_0005
Create Date: 2026-09-20
"""

from alembic import op

revision = "20260920_0006"
down_revision = "20260920_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_movie_qualities_normalized_title_trgm "
        "ON movie_qualities USING gist (normalized_title gist_trgm_ops) "
        "WHERE normalized_title IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_index(
        "ix_movie_qualities_normalized_title_trgm",
        table_name="movie_qualities",
    )
