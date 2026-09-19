from __future__ import annotations

from aiogram.types import Message

from cinegate.domain.archive import ArchiveMessage, MediaKind


def telegram_message_to_archive(message: Message) -> ArchiveMessage:
    """Convert a Telegram message without downloading any media."""

    if message.photo:
        media_kind = MediaKind.PHOTO
    elif message.video:
        media_kind = MediaKind.VIDEO
    elif message.document and (message.document.mime_type or "").startswith("video/"):
        media_kind = MediaKind.DOCUMENT
    else:
        media_kind = MediaKind.OTHER

    return ArchiveMessage(
        message_id=message.message_id,
        media_kind=media_kind,
        caption=message.caption,
    )
