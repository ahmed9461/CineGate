from __future__ import annotations

from typing import Any

from telethon import utils
from telethon.tl.types import MessageEmpty, MessageService

from cinegate.domain.archive import ArchiveMessage, MediaKind


def is_importable_message(message: Any) -> bool:
    return (
        message is not None
        and not isinstance(message, (MessageEmpty, MessageService))
        and int(getattr(message, "id", 0) or 0) > 0
    )


def telethon_message_to_archive(message: Any) -> ArchiveMessage:
    if getattr(message, "photo", None) is not None:
        media_kind = MediaKind.PHOTO
    elif getattr(message, "video", None) is not None:
        media_kind = MediaKind.VIDEO
    elif _is_video_document(message):
        media_kind = MediaKind.DOCUMENT
    else:
        media_kind = MediaKind.OTHER

    raw_text = getattr(message, "raw_text", None)
    return ArchiveMessage(
        message_id=int(message.id),
        media_kind=media_kind,
        caption=raw_text or None,
    )


def forwarded_source_message_id(
    message: Any,
    *,
    expected_source_channel_id: int,
) -> int | None:
    header = getattr(message, "fwd_from", None)
    if header is None:
        return None

    channel_post = getattr(header, "channel_post", None)
    if channel_post is None:
        return None

    source_chat_id = _forward_source_chat_id(message, header)
    if source_chat_id != expected_source_channel_id:
        return None

    return int(channel_post)


def _forward_source_chat_id(message: Any, header: Any) -> int | None:
    from_id = getattr(header, "from_id", None)
    if from_id is not None:
        try:
            return int(utils.get_peer_id(from_id))
        except (TypeError, ValueError):
            pass

    forward = getattr(message, "forward", None)
    chat_id = getattr(forward, "chat_id", None)
    return int(chat_id) if chat_id is not None else None


def _is_video_document(message: Any) -> bool:
    document = getattr(message, "document", None)
    if document is None:
        return False
    mime_type = getattr(document, "mime_type", None)
    return isinstance(mime_type, str) and mime_type.startswith("video/")
