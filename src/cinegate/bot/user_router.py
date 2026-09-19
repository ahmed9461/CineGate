from __future__ import annotations

import logging
from contextlib import suppress

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message
from sqlalchemy.exc import SQLAlchemyError

from cinegate.bot.callbacks import (
    MovieBackCallback,
    MovieSelectCallback,
    QualitySelectCallback,
)
from cinegate.bot.keyboards import (
    build_quality_keyboard,
    build_search_results_keyboard,
)
from cinegate.db.session import Database
from cinegate.domain.search import SearchQueryError
from cinegate.presentation.messages import (
    MOVIE_UNAVAILABLE,
    NO_SEARCH_RESULTS,
    STALE_SEARCH,
    WELCOME,
    render_search_results,
)
from cinegate.repositories.templates import MessageTemplateRepository
from cinegate.services.movie_search import MovieSearchService
from cinegate.services.search_sessions import SearchSessionService
from cinegate.services.text import normalize_title

logger = logging.getLogger(__name__)


def build_user_router(
    *,
    database: Database,
    search: MovieSearchService,
    sessions: SearchSessionService,
) -> Router:
    router = Router(name="users")

    @router.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
    async def start(message: Message) -> None:
        text = await _template(database, "welcome", WELCOME)
        await message.answer(text)

    @router.message(F.chat.type == ChatType.PRIVATE, F.text)
    async def direct_movie_search(message: Message, bot: Bot) -> None:
        if message.text is None or message.text.startswith("/"):
            return
        if message.from_user is None:
            return

        raw_query = message.text.strip()
        if not raw_query:
            return

        try:
            results = await search.search(raw_query)
        except SearchQueryError:
            results = ()

        normalized_query = normalize_title(raw_query)
        replacement = await sessions.replace(
            telegram_user_id=message.from_user.id,
            raw_query=raw_query[:128],
            normalized_query=normalized_query[:512],
            result_movie_ids=tuple(result.movie_id for result in results),
        )

        if results:
            default_text = render_search_results(len(results))
            text = await _template(database, "search_results", default_text)
            text = text.replace("%count%", str(len(results)))
            keyboard = build_search_results_keyboard(
                results,
                nonce=replacement.session.nonce,
            )
        else:
            text = await _template(database, "search_no_results", NO_SEARCH_RESULTS)
            keyboard = None

        sent = await message.answer(text, reply_markup=keyboard)
        try:
            stored = await sessions.set_result_message(
                telegram_user_id=message.from_user.id,
                nonce=replacement.session.nonce,
                message_id=sent.message_id,
            )
        except SQLAlchemyError:
            await _safe_delete(bot, message.chat.id, sent.message_id)
            raise
        if not stored:
            await _safe_delete(bot, message.chat.id, sent.message_id)
            return

        await _cleanup_previous_ui(
            bot=bot,
            chat_id=message.chat.id,
            result_message_id=replacement.previous_result_message_id,
            poster_message_id=replacement.previous_poster_message_id,
            exclude_message_id=sent.message_id,
        )

    @router.callback_query(MovieSelectCallback.filter())
    async def select_movie(
        callback: CallbackQuery,
        callback_data: MovieSelectCallback,
        bot: Bot,
    ) -> None:
        user_id = callback.from_user.id
        view = await search.get_movie_view(callback_data.movie_id)
        if view is None:
            await _safe_callback_answer(callback, MOVIE_UNAVAILABLE, show_alert=True)
            return

        claimed = await sessions.claim_movie(
            telegram_user_id=user_id,
            nonce=callback_data.nonce,
            movie_id=callback_data.movie_id,
        )
        if claimed is None:
            await _safe_callback_answer(callback, STALE_SEARCH)
            return

        await _safe_callback_answer(callback)

        try:
            copied = await bot.copy_message(
                chat_id=user_id,
                from_chat_id=view.archive_channel_id,
                message_id=view.poster_message_id,
                reply_markup=build_quality_keyboard(
                    view.qualities,
                    nonce=callback_data.nonce,
                    movie_id=view.movie_id,
                ),
            )
        except TelegramBadRequest:
            await sessions.reset_opening(
                telegram_user_id=user_id,
                nonce=callback_data.nonce,
                movie_id=callback_data.movie_id,
            )
            logger.warning(
                "Archive poster copy failed movie_id=%s source_message_id=%s",
                view.movie_id,
                view.poster_message_id,
                exc_info=True,
            )
            await bot.send_message(user_id, MOVIE_UNAVAILABLE)
            return
        except TelegramAPIError:
            await sessions.reset_opening(
                telegram_user_id=user_id,
                nonce=callback_data.nonce,
                movie_id=callback_data.movie_id,
            )
            raise

        try:
            completed = await sessions.complete_movie(
                telegram_user_id=user_id,
                nonce=callback_data.nonce,
                movie_id=callback_data.movie_id,
                poster_message_id=copied.message_id,
            )
        except SQLAlchemyError:
            await _safe_delete(bot, user_id, copied.message_id)
            raise
        if not completed:
            await _safe_delete(bot, user_id, copied.message_id)
            return

        if claimed.result_message_id is not None:
            await _safe_delete(bot, user_id, claimed.result_message_id)

    @router.callback_query(MovieBackCallback.filter())
    async def back_to_results(
        callback: CallbackQuery,
        callback_data: MovieBackCallback,
        bot: Bot,
    ) -> None:
        user_id = callback.from_user.id
        current = await sessions.get_current(
            telegram_user_id=user_id,
            nonce=callback_data.nonce,
        )
        if current is None or current.state != "movie":
            await _safe_callback_answer(callback, STALE_SEARCH)
            return

        results = await search.get_results_by_ids(current.result_movie_ids)
        if not results:
            await _safe_callback_answer(callback, STALE_SEARCH)
            return

        default_text = render_search_results(len(results))
        text = await _template(database, "search_results", default_text)
        text = text.replace("%count%", str(len(results)))

        claimed = await sessions.claim_back(
            telegram_user_id=user_id,
            nonce=callback_data.nonce,
        )
        if claimed is None:
            await _safe_callback_answer(callback, STALE_SEARCH)
            return

        await _safe_callback_answer(callback)

        try:
            sent = await bot.send_message(
                user_id,
                text,
                reply_markup=build_search_results_keyboard(
                    results,
                    nonce=callback_data.nonce,
                ),
            )
        except TelegramAPIError:
            await sessions.reset_returning(
                telegram_user_id=user_id,
                nonce=callback_data.nonce,
            )
            raise

        try:
            completed = await sessions.complete_back(
                telegram_user_id=user_id,
                nonce=callback_data.nonce,
                result_message_id=sent.message_id,
            )
        except SQLAlchemyError:
            await _safe_delete(bot, user_id, sent.message_id)
            raise
        if not completed:
            await _safe_delete(bot, user_id, sent.message_id)
            return

        if claimed.poster_message_id is not None:
            await _safe_delete(bot, user_id, claimed.poster_message_id)

    @router.callback_query(QualitySelectCallback.filter())
    async def select_quality(
        callback: CallbackQuery,
        callback_data: QualitySelectCallback,
    ) -> None:
        current = await sessions.get_current(
            telegram_user_id=callback.from_user.id,
            nonce=callback_data.nonce,
        )
        if (
            current is None
            or current.state != "movie"
            or current.selected_movie_id != callback_data.movie_id
        ):
            await _safe_callback_answer(callback, STALE_SEARCH)
            return

        view = await search.get_movie_view(callback_data.movie_id)
        if view is None or callback_data.quality not in view.qualities:
            await _safe_callback_answer(callback, MOVIE_UNAVAILABLE, show_alert=True)
            return

        await _safe_callback_answer(
            callback,
            "تم اختيار الجودة. سيتم ربطها بالإعلان في المرحلة التالية.",
        )

    return router


async def _template(database: Database, key: str, default: str) -> str:
    async with database.session() as session:
        return await MessageTemplateRepository(session).get_body(key, default)


async def _cleanup_previous_ui(
    *,
    bot: Bot,
    chat_id: int,
    result_message_id: int | None,
    poster_message_id: int | None,
    exclude_message_id: int,
) -> None:
    for message_id in (result_message_id, poster_message_id):
        if message_id is not None and message_id != exclude_message_id:
            await _safe_delete(bot, chat_id, message_id)


async def _safe_delete(bot: Bot, chat_id: int, message_id: int) -> None:
    with suppress(TelegramBadRequest):
        await bot.delete_message(chat_id=chat_id, message_id=message_id)


async def _safe_callback_answer(
    callback: CallbackQuery,
    text: str | None = None,
    *,
    show_alert: bool = False,
) -> None:
    with suppress(TelegramBadRequest):
        await callback.answer(text=text, show_alert=show_alert)
