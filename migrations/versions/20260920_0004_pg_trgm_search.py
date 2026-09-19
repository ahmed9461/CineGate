"""Enable trigram movie-title search.

Revision ID: 20260920_0004
Revises: 20260920_0003
Create Date: 2026-09-20
"""

from alembic import op

revision = "20260920_0004"
down_revision = "20260920_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX ix_movies_normalized_title_trgm "
        "ON movies USING gist (normalized_title gist_trgm_ops)"
    )


def downgrade() -> None:
    op.drop_index("ix_movies_normalized_title_trgm", table_name="movies")
