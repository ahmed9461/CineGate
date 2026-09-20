from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import delete

from cinegate.bot.archive_router import build_archive_router
from cinegate.db.models import ArchiveImportJob, ArchiveImportMessageMap
from cinegate.db.session import Database
from cinegate.domain.indexing import ArchiveIndexResult, IndexAction
from cinegate.repositories.import_jobs import ArchiveImportRepository

DATABASE_URL = os.getenv("CINEGATE_DATABASE_URL")
SOURCE_ID = -1001111111111
ARCHIVE_ID = -1002222222222


class FakeIndexer:
    def __init__(self) -> None:
        self.calls = []

    async def ingest(self, *, channel_id, message):
        self.calls.append((channel_id, message))
        return ArchiveIndexResult(
            action=IndexAction.QUALITY_UPSERTED,
            movie_id=123,
            display_title="Imported Movie",
            quality_count=1,
            owner_notification_quality_count=0,
        )


class FakeNotifier:
    def __init__(self) -> None:
        self.calls = []

    async def notify_movie(self, movie_id: int) -> None:
        self.calls.append(movie_id)


async def clean(database: Database) -> None:
    async with database.session() as session, session.begin():
        await session.execute(delete(ArchiveImportMessageMap))
        await session.execute(delete(ArchiveImportJob))


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


def fake_channel_post(message_id: int):
    return SimpleNamespace(
        message_id=message_id,
        chat=SimpleNamespace(id=ARCHIVE_ID),
        photo=None,
        video=object(),
        document=None,
        caption="Imported Movie 2025 #720p",
    )


def archive_handler(router):
    return next(
        item.callback
        for item in router.channel_post.handlers
        if item.callback.__name__ == "archive_channel_post"
    )


@pytest.mark.asyncio
async def test_running_historical_import_suppresses_only_owner_notice(
    database: Database,
) -> None:
    async with database.session() as session, session.begin():
        repository = ArchiveImportRepository(session)
        job = await repository.get_or_create_job(
            source_channel_id=SOURCE_ID,
            archive_channel_id=ARCHIVE_ID,
        )
        await repository.mark_running(job.id)

    indexer = FakeIndexer()
    notifier = FakeNotifier()
    router = build_archive_router(
        indexer,  # type: ignore[arg-type]
        notifier,  # type: ignore[arg-type]
        database=database,
    )

    await archive_handler(router)(fake_channel_post(100))

    assert len(indexer.calls) == 1
    assert notifier.calls == []


@pytest.mark.asyncio
async def test_owner_notice_resumes_when_import_is_paused(
    database: Database,
) -> None:
    async with database.session() as session, session.begin():
        repository = ArchiveImportRepository(session)
        job = await repository.get_or_create_job(
            source_channel_id=SOURCE_ID,
            archive_channel_id=ARCHIVE_ID,
        )
        await repository.mark_running(job.id)
        await repository.mark_paused(job.id, "manual pause")

    indexer = FakeIndexer()
    notifier = FakeNotifier()
    router = build_archive_router(
        indexer,  # type: ignore[arg-type]
        notifier,  # type: ignore[arg-type]
        database=database,
    )

    await archive_handler(router)(fake_channel_post(101))

    assert len(indexer.calls) == 1
    assert notifier.calls == [123]



@pytest.mark.asyncio
async def test_late_mapped_historical_message_stays_suppressed_after_completion(
    database: Database,
) -> None:
    async with database.session() as session, session.begin():
        repository = ArchiveImportRepository(session)
        job = await repository.get_or_create_job(
            source_channel_id=SOURCE_ID,
            archive_channel_id=ARCHIVE_ID,
        )
        await repository.initialize_snapshot(
            job_id=job.id,
            source_high_watermark_id=10,
            archive_baseline_message_id=99,
            source_total_estimate=1,
        )
        await repository.record_transfer_batch(
            job_id=job.id,
            processed_through_source_id=10,
            processed_count=1,
            skipped_count=0,
            forwarded_mappings=((10, 100),),
        )
        await repository.mark_running(job.id)
        await repository.mark_transferred(job.id)
        await repository.mark_reindexing(job.id)
        await repository.mark_completed(job.id)

    indexer = FakeIndexer()
    notifier = FakeNotifier()
    router = build_archive_router(
        indexer,  # type: ignore[arg-type]
        notifier,  # type: ignore[arg-type]
        database=database,
    )

    await archive_handler(router)(fake_channel_post(100))

    assert len(indexer.calls) == 1
    assert notifier.calls == []


@pytest.mark.asyncio
async def test_new_unmapped_archive_message_notifies_after_import_completed(
    database: Database,
) -> None:
    async with database.session() as session, session.begin():
        repository = ArchiveImportRepository(session)
        job = await repository.get_or_create_job(
            source_channel_id=SOURCE_ID,
            archive_channel_id=ARCHIVE_ID,
        )
        await repository.initialize_snapshot(
            job_id=job.id,
            source_high_watermark_id=10,
            archive_baseline_message_id=99,
            source_total_estimate=1,
        )
        await repository.record_transfer_batch(
            job_id=job.id,
            processed_through_source_id=10,
            processed_count=1,
            skipped_count=0,
            forwarded_mappings=((10, 100),),
        )
        await repository.mark_running(job.id)
        await repository.mark_transferred(job.id)
        await repository.mark_reindexing(job.id)
        await repository.mark_completed(job.id)

    indexer = FakeIndexer()
    notifier = FakeNotifier()
    router = build_archive_router(
        indexer,  # type: ignore[arg-type]
        notifier,  # type: ignore[arg-type]
        database=database,
    )

    await archive_handler(router)(fake_channel_post(101))

    assert len(indexer.calls) == 1
    assert notifier.calls == [123]
