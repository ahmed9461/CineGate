from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete, update

from cinegate.db.models import ArchiveImportJob, ArchiveImportMessageMap
from cinegate.db.session import Database
from cinegate.importer.errors import ImportAlreadyRunning
from cinegate.importer.lock import historical_import_lock
from cinegate.repositories.import_jobs import (
    ArchiveImportRepository,
    is_bulk_import_active,
)

DATABASE_URL = os.getenv("CINEGATE_DATABASE_URL")
SOURCE_ID = -1001111111111
ARCHIVE_ID = -1002222222222


async def clean_import_tables(database: Database) -> None:
    async with database.session() as session, session.begin():
        await session.execute(delete(ArchiveImportMessageMap))
        await session.execute(delete(ArchiveImportJob))


@pytest_asyncio.fixture
async def database() -> Database:
    if not DATABASE_URL:
        pytest.skip("CINEGATE_DATABASE_URL is not configured")

    database = Database(DATABASE_URL, pool_size=4, max_overflow=0)
    await clean_import_tables(database)
    try:
        yield database
    finally:
        await clean_import_tables(database)
        await database.dispose()


@pytest.mark.asyncio
async def test_job_pair_is_reused_and_snapshot_is_fixed_once(
    database: Database,
) -> None:
    async with database.session() as session, session.begin():
        repository = ArchiveImportRepository(session)
        first = await repository.get_or_create_job(
            source_channel_id=SOURCE_ID,
            archive_channel_id=ARCHIVE_ID,
        )
        initialized = await repository.initialize_snapshot(
            job_id=first.id,
            source_high_watermark_id=500,
            archive_baseline_message_id=100,
            source_total_estimate=450,
        )

    async with database.session() as session, session.begin():
        repository = ArchiveImportRepository(session)
        second = await repository.get_or_create_job(
            source_channel_id=SOURCE_ID,
            archive_channel_id=ARCHIVE_ID,
        )
        unchanged = await repository.initialize_snapshot(
            job_id=second.id,
            source_high_watermark_id=999,
            archive_baseline_message_id=999,
            source_total_estimate=999,
        )

    assert first.id == second.id
    assert initialized.source_high_watermark_id == 500
    assert unchanged.source_high_watermark_id == 500
    assert unchanged.archive_baseline_message_id == 100
    assert unchanged.source_total_estimate == 450


@pytest.mark.asyncio
async def test_transfer_batch_mapping_and_counters_are_idempotent(
    database: Database,
) -> None:
    async with database.session() as session, session.begin():
        repository = ArchiveImportRepository(session)
        job = await repository.get_or_create_job(
            source_channel_id=SOURCE_ID,
            archive_channel_id=ARCHIVE_ID,
        )
        await repository.record_transfer_batch(
            job_id=job.id,
            processed_through_source_id=12,
            processed_count=3,
            skipped_count=1,
            forwarded_mappings=((10, 1010), (12, 1012)),
        )

    async with database.session() as session, session.begin():
        repository = ArchiveImportRepository(session)
        await repository.record_transfer_batch(
            job_id=job.id,
            processed_through_source_id=12,
            processed_count=3,
            skipped_count=1,
            forwarded_mappings=((10, 1010), (12, 1012)),
        )
        snapshot = await repository.get_job(job.id)
        mapping_count = await repository.count_mappings(job.id)

    assert snapshot is not None
    assert snapshot.last_copied_source_message_id == 12
    assert snapshot.processed_messages == 3
    assert snapshot.skipped_messages == 1
    assert snapshot.copied_messages == 2
    assert mapping_count == 2


@pytest.mark.asyncio
async def test_reconciliation_mapping_is_idempotent(database: Database) -> None:
    async with database.session() as session, session.begin():
        repository = ArchiveImportRepository(session)
        job = await repository.get_or_create_job(
            source_channel_id=SOURCE_ID,
            archive_channel_id=ARCHIVE_ID,
        )
        inserted1 = await repository.record_reconciled_mappings(
            job_id=job.id,
            mappings=((20, 2020), (21, 2021)),
        )

    async with database.session() as session, session.begin():
        repository = ArchiveImportRepository(session)
        inserted2 = await repository.record_reconciled_mappings(
            job_id=job.id,
            mappings=((20, 2020), (21, 2021)),
        )
        snapshot = await repository.get_job(job.id)

    assert inserted1 == 2
    assert inserted2 == 0
    assert snapshot is not None
    assert snapshot.copied_messages == 2
    assert snapshot.reconciled_messages == 2


@pytest.mark.asyncio
async def test_reindex_checkpoint_and_counters_are_idempotent(
    database: Database,
) -> None:
    async with database.session() as session, session.begin():
        repository = ArchiveImportRepository(session)
        job = await repository.get_or_create_job(
            source_channel_id=SOURCE_ID,
            archive_channel_id=ARCHIVE_ID,
        )
        await repository.record_reconciled_mappings(
            job_id=job.id,
            mappings=((30, 3030), (31, 3031)),
        )
        await repository.mark_reindexed(
            job_id=job.id,
            source_message_id=30,
            missing=False,
        )
        await repository.mark_reindexed(
            job_id=job.id,
            source_message_id=31,
            missing=True,
        )

    async with database.session() as session, session.begin():
        repository = ArchiveImportRepository(session)
        await repository.mark_reindexed(
            job_id=job.id,
            source_message_id=30,
            missing=False,
        )
        await repository.mark_reindexed(
            job_id=job.id,
            source_message_id=31,
            missing=True,
        )
        snapshot = await repository.get_job(job.id)

    assert snapshot is not None
    assert snapshot.last_reindexed_source_message_id == 31
    assert snapshot.reindexed_messages == 1
    assert snapshot.missing_archive_messages == 1


@pytest.mark.asyncio
async def test_bulk_notification_suppression_only_for_active_work(
    database: Database,
) -> None:
    async with database.session() as session, session.begin():
        repository = ArchiveImportRepository(session)
        job = await repository.get_or_create_job(
            source_channel_id=SOURCE_ID,
            archive_channel_id=ARCHIVE_ID,
        )
        await repository.mark_running(job.id)

    async with database.session() as session:
        assert await is_bulk_import_active(session, ARCHIVE_ID)

    async with database.session() as session, session.begin():
        repository = ArchiveImportRepository(session)
        await repository.mark_paused(job.id, "temporary pause")

    async with database.session() as session:
        assert not await is_bulk_import_active(session, ARCHIVE_ID)

    async with database.session() as session, session.begin():
        repository = ArchiveImportRepository(session)
        await repository.mark_reindexing(job.id)

    async with database.session() as session:
        assert await is_bulk_import_active(session, ARCHIVE_ID)


@pytest.mark.asyncio
async def test_second_importer_for_same_pair_fails_fast(database: Database) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    async def hold_first() -> None:
        async with historical_import_lock(
            database,
            source_channel_id=SOURCE_ID,
            archive_channel_id=ARCHIVE_ID,
        ):
            entered.set()
            await release.wait()

    first = asyncio.create_task(hold_first())
    await entered.wait()

    try:
        with pytest.raises(ImportAlreadyRunning):
            async with historical_import_lock(
                database,
                source_channel_id=SOURCE_ID,
                archive_channel_id=ARCHIVE_ID,
            ):
                raise AssertionError("second importer must not enter")
    finally:
        release.set()
        await first



@pytest.mark.asyncio
async def test_invalid_import_status_transition_is_rejected(
    database: Database,
) -> None:
    async with database.session() as session, session.begin():
        repository = ArchiveImportRepository(session)
        job = await repository.get_or_create_job(
            source_channel_id=SOURCE_ID,
            archive_channel_id=ARCHIVE_ID,
        )

        with pytest.raises(RuntimeError, match="invalid import status transition"):
            await repository.mark_completed(job.id)



@pytest.mark.asyncio
async def test_stale_running_job_does_not_suppress_notifications_forever(
    database: Database,
) -> None:
    async with database.session() as session, session.begin():
        repository = ArchiveImportRepository(session)
        job = await repository.get_or_create_job(
            source_channel_id=SOURCE_ID,
            archive_channel_id=ARCHIVE_ID,
        )
        await repository.mark_running(job.id)
        await session.execute(
            update(ArchiveImportJob)
            .where(ArchiveImportJob.id == job.id)
            .values(updated_at=datetime.now(UTC) - timedelta(minutes=31))
        )

    async with database.session() as session:
        assert not await is_bulk_import_active(session, ARCHIVE_ID)
