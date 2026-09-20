from __future__ import annotations

import logging
import time
from collections.abc import Callable

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest

from cinegate.db.session import Database
from cinegate.repositories.import_jobs import (
    ArchiveImportRepository,
    ImportJobSnapshot,
)
from cinegate.repositories.settings import SettingsRepository

logger = logging.getLogger(__name__)

_TERMINAL_OR_PHASE_STATUSES = frozenset(
    {"paused", "transferred", "reindexing", "completed", "failed"}
)


class ImportProgressReporter:
    """CLI progress + optional single-message Telegram owner progress."""

    def __init__(
        self,
        *,
        database: Database,
        bot_token: str | None = None,
        telegram_min_interval: float = 5.0,
        printer: Callable[[str], None] = print,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if telegram_min_interval <= 0:
            raise ValueError("telegram_min_interval must be positive")

        self._database = database
        self._printer = printer
        self._monotonic = monotonic
        self._telegram_min_interval = telegram_min_interval
        self._bot = Bot(bot_token) if bot_token else None
        self._last_telegram_at = 0.0
        self._last_status: str | None = None

    async def __call__(self, job: ImportJobSnapshot) -> None:
        text = render_import_progress(job)
        self._printer(_render_cli_line(job))

        if self._bot is None:
            self._last_status = job.status
            return

        now = self._monotonic()
        status_changed = job.status != self._last_status
        force_update = (
            job.status in _TERMINAL_OR_PHASE_STATUSES
            and status_changed
        )
        if (
            job.owner_progress_message_id is not None
            and not force_update
            and now - self._last_telegram_at < self._telegram_min_interval
        ):
            self._last_status = job.status
            return

        owner_chat_id = await self._owner_chat_id()
        if owner_chat_id is None:
            self._last_status = job.status
            return

        try:
            if job.owner_progress_message_id is None:
                sent = await self._bot.send_message(owner_chat_id, text)
                await self._store_progress_message(job.id, sent.message_id)
            else:
                await self._bot.edit_message_text(
                    chat_id=owner_chat_id,
                    message_id=job.owner_progress_message_id,
                    text=text,
                )
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).casefold():
                logger.warning(
                    "Could not update historical-import owner progress",
                    exc_info=True,
                )
        except TelegramAPIError:
            logger.warning(
                "Could not update historical-import owner progress",
                exc_info=True,
            )
        else:
            self._last_telegram_at = now

        self._last_status = job.status

    async def close(self) -> None:
        if self._bot is not None:
            await self._bot.session.close()

    async def _owner_chat_id(self) -> int | None:
        async with self._database.session() as session:
            return await SettingsRepository(session).get_int("owner_chat_id")

    async def _store_progress_message(self, job_id, message_id: int) -> None:
        async with self._database.session() as session, session.begin():
            await ArchiveImportRepository(session).set_owner_progress_message(
                job_id=job_id,
                message_id=message_id,
            )


def render_import_progress(job: ImportJobSnapshot) -> str:
    total = (
        str(job.source_total_estimate)
        if job.source_total_estimate is not None
        else "?"
    )
    lines = [
        "📦 الاستيراد التاريخي — CineGate",
        "",
        f"الحالة: {_status_label(job.status)}",
        f"المعالجة: {job.processed_messages}/{total}",
        f"تم النقل: {job.copied_messages}",
        f"تم الاسترجاع بعد الانقطاع: {job.reconciled_messages}",
        f"تم التجاهل: {job.skipped_messages}",
        f"تمت إعادة الفهرسة: {job.reindexed_messages}",
        f"مفقود في الأرشيف: {job.missing_archive_messages}",
    ]
    if job.last_error:
        lines.extend(["", f"آخر خطأ: {job.last_error[:500]}"])
    return "\n".join(lines)


def _render_cli_line(job: ImportJobSnapshot) -> str:
    total = (
        str(job.source_total_estimate)
        if job.source_total_estimate is not None
        else "?"
    )
    return (
        f"[{job.status}] processed={job.processed_messages}/{total} "
        f"copied={job.copied_messages} reconciled={job.reconciled_messages} "
        f"reindexed={job.reindexed_messages} missing={job.missing_archive_messages}"
    )


def _status_label(status: str) -> str:
    return {
        "ready": "جاهز",
        "running": "جاري النقل",
        "paused": "متوقف مؤقتًا",
        "transferred": "اكتمل النقل",
        "reindexing": "جاري إعادة الفهرسة",
        "completed": "مكتمل ✅",
        "failed": "فشل ❌",
    }.get(status, status)
