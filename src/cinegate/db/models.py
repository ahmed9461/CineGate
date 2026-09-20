from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

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
    Uuid,
    func,
    text,
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
    owner_notification_message_id: Mapped[int | None] = mapped_column(BigInteger)
    owner_notification_quality_count: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        default=0,
    )
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


class UserSearchSession(Base):
    __tablename__ = "user_search_sessions"
    __table_args__ = (
        CheckConstraint(
            "state IN ('results', 'opening', 'movie', 'returning')",
            name="ck_user_search_sessions_state",
        ),
    )

    telegram_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    nonce: Mapped[str] = mapped_column(String(16), nullable=False)
    raw_query: Mapped[str] = mapped_column(String(128), nullable=False)
    normalized_query: Mapped[str] = mapped_column(String(512), nullable=False)
    result_movie_ids: Mapped[list[int]] = mapped_column(JSONB, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="results")
    selected_movie_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("movies.id", ondelete="SET NULL"),
    )
    result_message_id: Mapped[int | None] = mapped_column(BigInteger)
    poster_message_id: Mapped[int | None] = mapped_column(BigInteger)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class RewardSession(Base):
    __tablename__ = "reward_sessions"
    __table_args__ = (
        CheckConstraint(
            "status IN ("
            "'pending', 'client_completed', 'provider_confirmed', "
            "'rewarded', 'delivering', 'delivered', 'expired'"
            ")",
            name="ck_reward_sessions_status",
        ),
        Index(
            "uq_reward_sessions_active_user",
            "telegram_user_id",
            unique=True,
            postgresql_where=text(
                "status IN ("
                "'pending', 'client_completed', 'provider_confirmed', "
                "'rewarded', 'delivering'"
                ")"
            ),
        ),
        Index("ix_reward_sessions_user_created", "telegram_user_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    movie_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("movies.id", ondelete="CASCADE"),
        nullable=False,
    )
    movie_quality_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("movie_qualities.id", ondelete="CASCADE"),
        nullable=False,
    )
    quality: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    prompt_message_id: Mapped[int | None] = mapped_column(BigInteger)
    prompt_claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    client_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    rewarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Delivery(Base):
    __tablename__ = "deliveries"
    __table_args__ = (
        CheckConstraint(
            "status IN ("
            "'pending', 'sending', 'sent', 'deleting', 'deleted', 'delete_failed'"
            ")",
            name="ck_deliveries_status",
        ),
        UniqueConstraint("reward_session_id", name="uq_deliveries_reward_session"),
        Index("ix_deliveries_due", "status", "next_attempt_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    reward_session_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("reward_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    movie_quality_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("movie_qualities.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger)
    send_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delete_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delete_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
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


class OwnerEditSession(Base):
    __tablename__ = "owner_edit_sessions"
    __table_args__ = (
        CheckConstraint(
            "edit_kind IN ('setting', 'template')",
            name="ck_owner_edit_sessions_kind",
        ),
    )

    owner_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    edit_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    target_key: Mapped[str] = mapped_column(String(128), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
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


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_log"
    __table_args__ = (
        CheckConstraint(
            "target_type IN ('setting', 'template')",
            name="ck_admin_audit_log_target_type",
        ),
        Index(
            "ix_admin_audit_log_owner_created",
            "owner_user_id",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target_key: Mapped[str] = mapped_column(String(128), nullable=False)
    old_value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(
        JSONB
    )
    new_value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(
        JSONB
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )



class ArchiveImportJob(Base):
    __tablename__ = "archive_import_jobs"
    __table_args__ = (
        UniqueConstraint(
            "source_channel_id",
            "archive_channel_id",
            name="uq_archive_import_jobs_source_archive",
        ),
        CheckConstraint(
            "status IN ("
            "'ready', 'running', 'paused', 'transferred', "
            "'reindexing', 'completed', 'failed'"
            ")",
            name="ck_archive_import_jobs_status",
        ),
        Index(
            "ix_archive_import_jobs_archive_status",
            "archive_channel_id",
            "status",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    source_channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    archive_channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ready")
    source_high_watermark_id: Mapped[int | None] = mapped_column(BigInteger)
    archive_baseline_message_id: Mapped[int | None] = mapped_column(BigInteger)
    last_copied_source_message_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
    )
    last_reindexed_source_message_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
    )
    source_total_estimate: Mapped[int | None] = mapped_column(BigInteger)
    processed_messages: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    copied_messages: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    reconciled_messages: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
    )
    skipped_messages: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    reindexed_messages: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
    )
    missing_archive_messages: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
    )
    owner_progress_message_id: Mapped[int | None] = mapped_column(BigInteger)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
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


class ArchiveImportMessageMap(Base):
    __tablename__ = "archive_import_message_map"
    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "archive_message_id",
            name="uq_archive_import_map_job_archive_message",
        ),
        Index(
            "ix_archive_import_map_job_source",
            "job_id",
            "source_message_id",
        ),
    )

    job_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("archive_import_jobs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    source_message_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    archive_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    copied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    reindexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
