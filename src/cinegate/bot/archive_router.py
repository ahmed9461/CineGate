from __future__ import annotations

import logging

from aiogram import Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message

from cinegate.bot.adapters import telegram_message_to_archive
from cinegate.services.archive_indexer import ArchiveIndexService
from cinegate.services.owner_notifier import OwnerArchiveNotifier

logger = logging.getLogger(__name__)


def build_archive_router(
    indexer: ArchiveIndexService,
    notifier: OwnerArchiveNotifier,
) -> Router:
    router = Router(name="archive")

    @router.channel_post()
    async def archive_channel_post(message: Message) -> None:
        result = await indexer.ingest(
            channel_id=message.chat.id,
            message=telegram_message_to_archive(message),
        )

        if not result.should_notify_owner or result.movie_id is None:
            return

        try:
            await notifier.notify_movie(result.movie_id)
        except TelegramAPIError:
            # Indexing already committed. Owner notification is useful but
            # must never roll back or corrupt archived movie data.
            logger.warning(
                "Owner archive notification failed for movie_id=%s",
                result.movie_id,
                exc_info=True,
            )

    return router
