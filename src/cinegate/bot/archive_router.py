from __future__ import annotations

import logging

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import Message

from cinegate.bot.adapters import telegram_message_to_archive
from cinegate.db.session import Database
from cinegate.repositories.import_jobs import (
    is_bulk_import_active,
    is_historical_import_message,
)
from cinegate.services.archive_indexer import ArchiveIndexService
from cinegate.services.owner_notifier import OwnerArchiveNotifier

logger = logging.getLogger(__name__)


def build_archive_router(
    indexer: ArchiveIndexService,
    notifier: OwnerArchiveNotifier,
    *,
    database: Database | None = None,
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

        if database is not None:
            async with database.session() as session:
                if await is_historical_import_message(
                    session,
                    archive_channel_id=message.chat.id,
                    archive_message_id=message.message_id,
                ):
                    return
                if await is_bulk_import_active(session, message.chat.id):
                    return

        try:
            await notifier.notify_movie(result.movie_id)
        except (TelegramBadRequest, TelegramForbiddenError):
            # Permanent Telegram-side notification problems should not make
            # Telegram retry an archive update forever. The durable notified
            # count stays behind, so a later valid update/configuration can
            # attempt the notification again.
            logger.warning(
                "Permanent owner archive notification failure movie_id=%s",
                result.movie_id,
                exc_info=True,
            )

    return router
