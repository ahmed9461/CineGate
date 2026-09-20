from __future__ import annotations

import os
from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import delete

from cinegate.db.models import (
    AppSetting,
    ArchiveImportJob,
    ArchiveImportMessageMap,
)
from cinegate.db.session import Database
from cinegate.importer.progress import ImportProgressReporter, render_import_progress
from cinegate.repositories.import_jobs import (
    ArchiveImportRepository,
    ImportJobSnapshot,
)
from cinegate.repositories.settings import SettingsRepository

DATABASE_URL = os.getenv("CINEGATE_DATABASE_URL")
SOURCE_ID = -1001111111111
ARCHIVE_ID = -1002222222222
OWNER_CHAT_ID = 777


class FakeSession:
    async def close(self) -> None:
        return None


class FakeBot:
    def __init__(self) -> None:
        self.session = FakeSession()
        self.sent = []
        self.edited = []

    async def send_message(self, chat_id: int, text: str):
        self.sent.append((chat_id, text))
        return SimpleNamespace(message_id=900)

    async def edit_message_text(self, *, chat_id: int, message_id: int, text: str):
        self.edited.append((chat_id, message_id, text))


async def clean(database: Database) -> None:
    async with database.session() as session, session.begin():
        await session.execute(delete(ArchiveImportMessageMap))
        await session.execute(delete(ArchiveImportJob))
        await session.execute(delete(AppSetting))


@pytest_asyncio.fixture
async def database() -> Database:
    if not DATABASE_URL:
        pytest.skip("CINEGATE_DATABASE_URL is not configured")

    database = Database(DATABASE_URL, pool_size=2, max_overflow=0)
    await clean(database)
    try:
        yield database
    finally:
        await clean(database)
        await database.dispose()


@pytest.mark.asyncio
async def test_progress_uses_one_rate_limited_owner_message(database: Database) -> None:
    async with database.session() as session, session.begin():
        await SettingsRepository(session).set("owner_chat_id", OWNER_CHAT_ID)
        repository = ArchiveImportRepository(session)
        job = await repository.get_or_create_job(
            source_channel_id=SOURCE_ID,
            archive_channel_id=ARCHIVE_ID,
        )
        await repository.initialize_snapshot(
            job_id=job.id,
            source_high_watermark_id=100,
            archive_baseline_message_id=50,
            source_total_estimate=100,
        )
        running = await repository.mark_running(job.id)

    clock = [10.0]

    def monotonic() -> float:
        return clock[0]

    printed = []
    reporter = ImportProgressReporter(
        database=database,
        bot_token=None,
        telegram_min_interval=5.0,
        printer=printed.append,
        monotonic=monotonic,
    )
    fake_bot = FakeBot()
    reporter._bot = fake_bot  # type: ignore[assignment]

    await reporter(running)

    async with database.session() as session:
        stored = await ArchiveImportRepository(session).get_job(job.id)
    assert stored is not None
    assert stored.owner_progress_message_id == 900
    assert len(fake_bot.sent) == 1

    quiet_update = replace(
        stored,
        processed_messages=25,
        copied_messages=25,
    )
    clock[0] = 12.0
    await reporter(quiet_update)

    assert fake_bot.edited == []

    completed = replace(
        quiet_update,
        status="completed",
        processed_messages=100,
        copied_messages=95,
        reconciled_messages=2,
        skipped_messages=5,
        reindexed_messages=94,
        missing_archive_messages=1,
    )
    clock[0] = 13.0
    await reporter(completed)

    assert len(fake_bot.edited) == 1
    assert fake_bot.edited[0][0:2] == (OWNER_CHAT_ID, 900)
    assert "تم النقل: 95" in fake_bot.edited[0][2]
    assert "تمت إعادة الفهرسة: 94" in fake_bot.edited[0][2]
    assert "مفقود في الأرشيف: 1" in fake_bot.edited[0][2]
    assert len(printed) == 3

    await reporter.close()


def test_final_progress_text_contains_all_import_counters() -> None:
    job = ImportJobSnapshot(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        source_channel_id=SOURCE_ID,
        archive_channel_id=ARCHIVE_ID,
        status="completed",
        source_high_watermark_id=100,
        archive_baseline_message_id=50,
        last_copied_source_message_id=100,
        last_reindexed_source_message_id=100,
        source_total_estimate=100,
        processed_messages=100,
        copied_messages=95,
        reconciled_messages=2,
        skipped_messages=5,
        reindexed_messages=94,
        missing_archive_messages=1,
        owner_progress_message_id=900,
        started_at=None,
        completed_at=None,
        last_error=None,
    )

    text = render_import_progress(job)

    assert "المعالجة: 100/100" in text
    assert "تم النقل: 95" in text
    assert "تم الاسترجاع بعد الانقطاع: 2" in text
    assert "تم التجاهل: 5" in text
    assert "تمت إعادة الفهرسة: 94" in text
    assert "مفقود في الأرشيف: 1" in text
