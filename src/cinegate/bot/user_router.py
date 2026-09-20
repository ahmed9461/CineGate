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
    build_reward_keyboard,
    build_search_results_keyboard,
)
from cinegate.db.session import Database
from cinegate.domain.rewards import ActiveRewardConflict, RewardQualityUnavailable
from cinegate.domain.search import SearchQueryError
from cinegate.repositories.settings import SettingsRepository
from cinegate.services.movie_search import MovieSearchService
from cinegate.services.reward_sessions import RewardSessionService
from cinegate.services.search_sessions import SearchSessionService
from cinegate.services.templates import TemplateService
from cinegate.services.text import normalize_title

logger = logging.getLogger(__name__)


def build_user_router(
    *,
    database: Database,
    search: MovieSearchService,
    sessions: SearchSessionService,
    rewards: RewardSessionService,
    templates: TemplateService,
) -> Router:
    router = Router(name="users")

    @router.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
    async def start(message: Message) -> None:
        rendered = await templates.render("welcome")
        await message.answer(
            rendered.text,
            entities=list(rendered.entities) or None,
        )

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
            rendered = await templates.render(
                "search_results",
                {"%count%": str(len(results))},
            )
            keyboard = build_search_results_keyboard(
                results,
                nonce=replacement.session.nonce,
            )
        else:
            rendered = await templates.render("search_no_results")
            keyboard = None

        sent = await message.answer(
            rendered.text,
            entities=list(rendered.entities) or None,
            reply_markup=keyboard,
        )
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
            rendered = await templates.render("movie_unavailable")
            await _safe_callback_answer(
                callback,
                rendered.text,
                show_alert=True,
            )
            return

        claimed = await sessions.claim_movie(
            telegram_user_id=user_id,
            nonce=callback_data.nonce,
            movie_id=callback_data.movie_id,
        )
        if claimed is None:
            rendered = await templates.render("stale_search")
            await _safe_callback_answer(callback, rendered.text)
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
            rendered = await templates.render("movie_unavailable")
            await bot.send_message(
                user_id,
                rendered.text,
                entities=list(rendered.entities) or None,
            )
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
            rendered = await templates.render("stale_search")
            await _safe_callback_answer(callback, rendered.text)
            return

        results = await search.get_results_by_ids(current.result_movie_ids)
        if not results:
            rendered = await templates.render("stale_search")
            await _safe_callback_answer(callback, rendered.text)
            return

        rendered = await templates.render(
            "search_results",
            {"%count%": str(len(results))},
        )

        claimed = await sessions.claim_back(
            telegram_user_id=user_id,
            nonce=callback_data.nonce,
        )
        if claimed is None:
            rendered = await templates.render("stale_search")
            await _safe_callback_answer(callback, rendered.text)
            return

        await _safe_callback_answer(callback)

        try:
            sent = await bot.send_message(
                user_id,
                rendered.text,
                entities=list(rendered.entities) or None,
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
        bot: Bot,
    ) -> None:
        user_id = callback.from_user.id
        current = await sessions.get_current(
            telegram_user_id=user_id,
            nonce=callback_data.nonce,
        )
        if (
            current is None
            or current.state != "movie"
            or current.selected_movie_id != callback_data.movie_id
        ):
            rendered = await templates.render("stale_search")
            await _safe_callback_answer(callback, rendered.text)
            return

        view = await search.get_movie_view(callback_data.movie_id)
        if view is None or callback_data.quality not in view.qualities:
            rendered = await templates.render("movie_unavailable")
            await _safe_callback_answer(
                callback,
                rendered.text,
                show_alert=True,
            )
            return

        reward_config = await _reward_config(database)
        if reward_config is None:
            rendered = await templates.render("reward_not_configured")
            await _safe_callback_answer(
                callback,
                rendered.text,
                show_alert=True,
            )
            return

        public_base_url, _block_id = reward_config

        try:
            reward, _created = await rewards.get_or_create(
                telegram_user_id=user_id,
                movie_id=view.movie_id,
                quality=callback_data.quality,
            )
        except ActiveRewardConflict as exc:
            rendered = await templates.render(
                "active_reward_conflict",
                {"%quality%": exc.session.quality},
            )
            await _safe_callback_answer(
                callback,
                rendered.text,
                show_alert=True,
            )
            return
        except RewardQualityUnavailable:
            rendered = await templates.render("movie_unavailable")
            await _safe_callback_answer(
                callback,
                rendered.text,
                show_alert=True,
            )
            return

        claimed = await rewards.claim_prompt(
            session_id=reward.id,
            telegram_user_id=user_id,
        )
        if not claimed:
            await _safe_callback_answer(
                callback,
                "طلب الإعلان جاهز بالفعل.",
            )
            return

        await _safe_callback_answer(callback, "جاري تجهيز الإعلان...")

        rendered_prompt = await templates.render(
            "reward_prompt",
            {
                "%movie%": view.display_title,
                "%quality%": callback_data.quality,
            },
        )
        miniapp_url = (
            f"{public_base_url.rstrip('/')}/miniapp/reward/{reward.id}"
        )

        try:
            sent = await bot.send_message(
                user_id,
                rendered_prompt.text,
                entities=list(rendered_prompt.entities) or None,
                reply_markup=build_reward_keyboard(miniapp_url),
            )
        except TelegramAPIError:
            await rewards.reset_prompt_claim(
                session_id=reward.id,
                telegram_user_id=user_id,
            )
            raise

        try:
            stored = await rewards.complete_prompt(
                session_id=reward.id,
                telegram_user_id=user_id,
                message_id=sent.message_id,
            )
        except SQLAlchemyError:
            await _safe_delete(bot, user_id, sent.message_id)
            raise

        if not stored:
            await _safe_delete(bot, user_id, sent.message_id)

    return router


async def _reward_config(database: Database) -> tuple[str, str] | None:
    async with database.session() as session:
        values = await SettingsRepository(session).get_many(
            ("public_base_url", "adsgram_block_id")
        )

    public_base_url = values.get("public_base_url")
    block_id = values.get("adsgram_block_id")
    if not isinstance(public_base_url, str) or not public_base_url.startswith(
        "https://"
    ):
        return None
    if not isinstance(block_id, str) or not block_id.strip():
        return None
    return public_base_url.rstrip("/"), block_id.strip()


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
    with suppress(TelegramAPIError):
        await bot.delete_message(chat_id=chat_id, message_id=message_id)


async def _safe_callback_answer(
    callback: CallbackQuery,
    text: str | None = None,
    *,
    show_alert: bool = False,
) -> None:
    with suppress(TelegramAPIError):
        await callback.answer(text=text, show_alert=show_alert)
