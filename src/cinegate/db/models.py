from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cinegate.db.base import Base


class Movie(Base):
    __tablename__ = "movies"
    __table_args__ = (
        UniqueConstraint(
            "archive_channel_id",
            "poster_message_id",
            name="uq_movies_archive_poster",
        ),
        CheckConstraint(
            "parser_style IN ('modern', 'legacy')",
            name="ck_movies_parser_style",
        ),
        CheckConstraint(
            "status IN ('pending', 'indexed', 'orphan', 'ambiguous')",
            name="ck_movies_status",
        ),
        CheckConstraint(
            "parser_confidence BETWEEN 0 AND 100",
            name="ck_movies_confidence",
        ),
        Index("ix_movies_normalized_title_status", "normalized_title", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    archive_channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    poster_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    display_title: Mapped[str] = mapped_column(String(512), nullable=False)
    normalized_title: Mapped[str] = mapped_column(String(512), nullable=False)
    year: Mapped[int | None] = mapped_column(SmallInteger)
    parser_style: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    raw_poster_caption: Mapped[str] = mapped_column(Text, nullable=False)
    parser_confidence: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    qualities: Mapped[list[MovieQuality]] = relationship(
        back_populates="movie",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class MovieQuality(Base):
    __tablename__ = "movie_qualities"
    __table_args__ = (
        UniqueConstraint(
            "archive_channel_id",
            "archive_message_id",
            name="uq_movie_qualities_archive_message",
        ),
        UniqueConstraint("movie_id", "quality", name="uq_movie_qualities_movie_quality"),
        CheckConstraint(
            "parser_confidence BETWEEN 0 AND 100",
            name="ck_movie_qualities_confidence",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    movie_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("movies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    archive_channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    archive_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    quality: Mapped[str] = mapped_column(String(16), nullable=False)
    raw_caption: Mapped[str] = mapped_column(Text, nullable=False)
    extracted_title: Mapped[str | None] = mapped_column(String(512))
    normalized_title: Mapped[str | None] = mapped_column(String(512))
    extracted_year: Mapped[int | None] = mapped_column(SmallInteger)
    parser_confidence: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    movie: Mapped[Movie] = relationship(back_populates="qualities")


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(
        JSONB,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class MessageTemplate(Base):
    __tablename__ = "message_templates"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    entities: Mapped[list[dict] | None] = mapped_column(JSONB)
    rich_message: Mapped[dict | None] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
