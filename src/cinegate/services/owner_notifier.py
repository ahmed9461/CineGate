from __future__ import annotations

import logging
from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from sqlalchemy import func, select, update

from cinegate.db.models import Movie, MovieQuality
from cinegate.db.session import Database
from cinegate.repositories.settings import SettingsRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _NoticeState:
    owner_chat_id: int
    movie_id: int
    display_title: str
    quality_count: int
    notification_message_id: int | None


class OwnerArchiveNotifier:
    """Keep one owner notification per movie updated with quality count."""

    def __init__(self, database: Database, bot: Bot) -> None:
        self._database = database
        self._bot = bot

    async def notify_movie(self, movie_id: int) -> None:
        # Two passes are enough to converge if another quality commits while
        # the first Telegram request is in flight, without an unbounded loop.
        for _ in range(2):
            state = await self._load_state(movie_id)
            if state is None or state.quality_count == 0:
                return

            text = self._render(state)
            if state.notification_message_id is None:
                sent = await self._bot.send_message(state.owner_chat_id, text)
                stored_id = await self._store_notification_id(movie_id, sent.message_id)
                if stored_id != sent.message_id:
                    await self._delete_duplicate_notice(
                        chat_id=state.owner_chat_id,
                        message_id=sent.message_id,
                    )
            else:
                await self._edit_notice(
                    chat_id=state.owner_chat_id,
                    message_id=state.notification_message_id,
                    text=text,
                )

            latest = await self._load_state(movie_id)
            if latest is None or latest.quality_count == state.quality_count:
                return

    async def _load_state(self, movie_id: int) -> _NoticeState | None:
        async with self._database.session() as session:
            owner_chat_id = await SettingsRepository(session).get_int("owner_chat_id")
            if owner_chat_id is None:
                return None

            row = (
                await session.execute(
                    select(
                        Movie.id,
                        Movie.display_title,
                        Movie.owner_notification_message_id,
                        func.count(MovieQuality.id).label("quality_count"),
                    )
                    .outerjoin(MovieQuality, MovieQuality.movie_id == Movie.id)
                    .where(Movie.id == movie_id)
                    .group_by(Movie.id)
                )
            ).one_or_none()

            if row is None:
                return None

            return _NoticeState(
                owner_chat_id=owner_chat_id,
                movie_id=row.id,
                display_title=row.display_title,
                quality_count=int(row.quality_count or 0),
                notification_message_id=row.owner_notification_message_id,
            )

    async def _store_notification_id(self, movie_id: int, message_id: int) -> int:
        async with self._database.session() as session, session.begin():
                stored = await session.scalar(
                    update(Movie)
                    .where(
                        Movie.id == movie_id,
                        Movie.owner_notification_message_id.is_(None),
                    )
                    .values(owner_notification_message_id=message_id)
                    .returning(Movie.owner_notification_message_id)
                )
                if stored is not None:
                    return int(stored)

                existing = await session.scalar(
                    select(Movie.owner_notification_message_id).where(Movie.id == movie_id)
                )
                return int(existing or message_id)

    async def _edit_notice(self, *, chat_id: int, message_id: int, text: str) -> None:
        try:
            await self._bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
            )
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).casefold():
                raise

    async def _delete_duplicate_notice(self, *, chat_id: int, message_id: int) -> None:
        try:
            await self._bot.delete_message(chat_id=chat_id, message_id=message_id)
        except TelegramAPIError:
            logger.warning(
                "Could not delete duplicate owner notification chat_id=%s message_id=%s",
                chat_id,
                message_id,
                exc_info=True,
            )

    @staticmethod
    def _render(state: _NoticeState) -> str:
        return (
            "✅ تم حفظ منشورات جديدة\n\n"
            f"1- {state.display_title} ({state.quality_count})"
        )
