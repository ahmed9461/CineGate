"""Initial CineGate archive/settings schema.

Revision ID: 20260920_0001
Revises:
Create Date: 2026-09-20
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260920_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "movies",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("archive_channel_id", sa.BigInteger(), nullable=False),
        sa.Column("poster_message_id", sa.BigInteger(), nullable=False),
        sa.Column("display_title", sa.String(length=512), nullable=False),
        sa.Column("normalized_title", sa.String(length=512), nullable=False),
        sa.Column("year", sa.SmallInteger(), nullable=True),
        sa.Column("parser_style", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("raw_poster_caption", sa.Text(), nullable=False),
        sa.Column("parser_confidence", sa.SmallInteger(), nullable=False),
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
            "parser_confidence BETWEEN 0 AND 100",
            name="ck_movies_confidence",
        ),
        sa.CheckConstraint(
            "parser_style IN ('modern', 'legacy')",
            name="ck_movies_parser_style",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'indexed', 'orphan', 'ambiguous')",
            name="ck_movies_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "archive_channel_id",
            "poster_message_id",
            name="uq_movies_archive_poster",
        ),
    )
    op.create_index(
        "ix_movies_normalized_title_status",
        "movies",
        ["normalized_title", "status"],
        unique=False,
    )

    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key"),
    )

    op.create_table(
        "message_templates",
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("entities", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("rich_message", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key"),
    )

    op.create_table(
        "movie_qualities",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("movie_id", sa.BigInteger(), nullable=False),
        sa.Column("archive_channel_id", sa.BigInteger(), nullable=False),
        sa.Column("archive_message_id", sa.BigInteger(), nullable=False),
        sa.Column("quality", sa.String(length=16), nullable=False),
        sa.Column("raw_caption", sa.Text(), nullable=False),
        sa.Column("extracted_title", sa.String(length=512), nullable=True),
        sa.Column("normalized_title", sa.String(length=512), nullable=True),
        sa.Column("extracted_year", sa.SmallInteger(), nullable=True),
        sa.Column("parser_confidence", sa.SmallInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "parser_confidence BETWEEN 0 AND 100",
            name="ck_movie_qualities_confidence",
        ),
        sa.ForeignKeyConstraint(["movie_id"], ["movies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "archive_channel_id",
            "archive_message_id",
            name="uq_movie_qualities_archive_message",
        ),
        sa.UniqueConstraint(
            "movie_id",
            "quality",
            name="uq_movie_qualities_movie_quality",
        ),
    )
    op.create_index(
        "ix_movie_qualities_movie_id",
        "movie_qualities",
        ["movie_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_movie_qualities_movie_id", table_name="movie_qualities")
    op.drop_table("movie_qualities")
    op.drop_table("message_templates")
    op.drop_table("app_settings")
    op.drop_index("ix_movies_normalized_title_status", table_name="movies")
    op.drop_table("movies")
