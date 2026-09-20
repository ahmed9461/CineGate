from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest

from cinegate.domain.delivery import DueDeletion
from cinegate.services.delivery import DeliveryService

logger = logging.getLogger(__name__)


class DeliveryDeletionWorker:
    """Lightweight in-process worker for durable Telegram movie deletion."""

    def __init__(
        self,
        *,
        delivery_service: DeliveryService,
        bot: Bot,
        poll_seconds: float = 1.0,
        batch_size: int = 50,
        concurrency: int = 10,
    ) -> None:
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        self._delivery_service = delivery_service
        self._bot = bot
        self._poll_seconds = poll_seconds
        self._batch_size = max(1, min(100, batch_size))
        self._concurrency = max(1, min(25, concurrency))

    async def run(self, stop_event: asyncio.Event) -> None:
        await self._delivery_service.recover_stale_sends()
        await self._delivery_service.recover_stale_deletions()

        while not stop_event.is_set():
            due = await self._delivery_service.claim_due_deletions(
                limit=self._batch_size
            )
            if due:
                semaphore = asyncio.Semaphore(self._concurrency)
                await asyncio.gather(
                    *(
                        self._delete_with_semaphore(item, semaphore)
                        for item in due
                    )
                )
                continue

            with suppress(TimeoutError):
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=self._poll_seconds,
                )

    async def _delete_with_semaphore(
        self,
        item: DueDeletion,
        semaphore: asyncio.Semaphore,
    ) -> None:
        async with semaphore:
            await self._delete_one(item)

    async def _delete_one(self, item: DueDeletion) -> None:
        try:
            await self._bot.delete_message(
                chat_id=item.telegram_user_id,
                message_id=item.telegram_message_id,
            )
        except TelegramBadRequest:
            # The user may already have deleted the message. Either way there
            # is nothing useful left for CineGate to delete.
            await self._delivery_service.mark_deleted(item.delivery_id)
        except TelegramAPIError as exc:
            logger.warning(
                "Movie deletion failed delivery_id=%s",
                item.delivery_id,
                exc_info=True,
            )
            await self._delivery_service.reschedule_delete(
                item.delivery_id,
                str(exc),
            )
        else:
            await self._delivery_service.mark_deleted(item.delivery_id)
