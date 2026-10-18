from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from cinegate.db.base import Base


class ArchiveMessageSnapshot(Base):
    """Latest observed Telegram message, including parser interruption boundaries."""

    __tablename__ = "archive_message_snapshots"
    __table_args__ = (
        CheckConstraint(
            "media_kind IN ('photo', 'video', 'document', 'other')",
            name="ck_archive_message_snapshots_media_kind",
        ),
    )

    archive_channel_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    message_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    media_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    caption: Mapped[str | None] = mapped_column(Text)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    conflicted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
