from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select

from cinegate.db.models import (
    AppSetting,
    ArchiveImportJob,
    ArchiveImportMessageMap,
    Movie,
    MovieQuality,
)
from cinegate.db.session import Database
from cinegate.importer.adapter import telethon_message_to_archive
from cinegate.importer.service import HistoricalImportService
from cinegate.repositories.import_jobs import ArchiveImportRepository
from cinegate.repositories.settings import SettingsRepository
from cinegate.services.archive_indexer import ArchiveIndexService

DATABASE_URL = os.getenv("CINEGATE_DATABASE_URL")
SOURCE_ID = -1001111111111
ARCHIVE_ID = -1002222222222


def archive_message(
    message_id: int,
    *,
    photo=False,
    video=False,
    text: str | None = None,
):
    return SimpleNamespace(
        id=message_id,
        photo=object() if photo else None,
        video=object() if video else None,
        document=None,
        raw_text=text,
        fwd_from=None,
        forward=None,
    )


class ReindexGateway:
    def __init__(self, messages: dict[int, object | None]) -> None:
        self.archive = object()
        self.messages = messages
        self.requested_batches: list[tuple[int, ...]] = []

    async def resolve_channel(self, channel_id):
        assert channel_id == ARCHIVE_ID
        return self.archive

    async def get_messages_by_ids(self, entity, message_ids):
        assert entity is self.archive
        self.requested_batches.append(tuple(message_ids))
        return tuple(self.messages.get(message_id) for message_id in message_ids)


async def clean(database: Database) -> None:
    async with database.session() as session, session.begin():
        await session.execute(delete(ArchiveImportMessageMap))
        await session.execute(delete(ArchiveImportJob))
        await session.execute(delete(MovieQuality))
        await session.execute(delete(Movie))
        await session.execute(delete(AppSetting))


@pytest_asyncio.fixture
async def database() -> Database:
    if not DATABASE_URL:
        pytest.skip("CINEGATE_DATABASE_URL is not configured")

    database = Database(DATABASE_URL, pool_size=3, max_overflow=0)
    await clean(database)
    try:
        yield database
    finally:
        await clean(database)
        await database.dispose()


async def seed_job_and_mappings(database: Database):
    async with database.session() as session, session.begin():
        await SettingsRepository(session).set("archive_channel_id", ARCHIVE_ID)
        repository = ArchiveImportRepository(session)
        job = await repository.get_or_create_job(
            source_channel_id=SOURCE_ID,
            archive_channel_id=ARCHIVE_ID,
        )
        await repository.initialize_snapshot(
            job_id=job.id,
            source_high_watermark_id=3,
            archive_baseline_message_id=100,
            source_total_estimate=3,
        )
        await repository.record_reconciled_mappings(
            job_id=job.id,
            mappings=((1, 101), (2, 102), (3, 103)),
        )
        await repository.mark_running(job.id)
        await repository.mark_transferred(job.id)
        return job.id


@pytest.mark.asyncio
async def test_reindex_replays_mapping_in_source_order_and_completes(
    database: Database,
) -> None:
    job_id = await seed_job_and_mappings(database)
    gateway = ReindexGateway(
        {
            101: archive_message(
                101,
                photo=True,
                text="الفيلم: Interstellar\nالسنة: 2014\nالقصة: قصة",
            ),
            102: archive_message(
                102,
                video=True,
                text="Interstellar 2014 #720p",
            ),
            103: archive_message(
                103,
                video=True,
                text="Interstellar 2014 #1080p",
            ),
        }
    )
    progress = []

    async def report(job):
        progress.append((job.status, job.last_reindexed_source_message_id))

    service = HistoricalImportService(
        database=database,
        gateway=gateway,  # type: ignore[arg-type]
        reindex_batch_size=2,
        progress_callback=report,
    )

    completed = await service.reindex(job_id=job_id, full=False)

    assert completed.status == "completed"
    assert completed.last_reindexed_source_message_id == 3
    assert completed.reindexed_messages == 3
    assert gateway.requested_batches == [(101, 102), (103,)]
    assert progress[0][0] == "reindexing"
    assert progress[-1][0] == "completed"

    async with database.session() as session:
        movie_count = await session.scalar(select(func.count(Movie.id)))
        quality_count = await session.scalar(select(func.count(MovieQuality.id)))
        movie = await session.scalar(select(Movie))

    assert movie_count == 1
    assert quality_count == 2
    assert movie is not None
    assert movie.status == "indexed"


@pytest.mark.asyncio
async def test_reindex_resume_starts_after_checkpoint(database: Database) -> None:
    job_id = await seed_job_and_mappings(database)

    async with database.session() as session, session.begin():
        repository = ArchiveImportRepository(session)
        await repository.mark_reindexing(job_id)
        await repository.mark_reindexed(
            job_id=job_id,
            source_message_id=1,
            missing=False,
        )

    gateway = ReindexGateway(
        {
            102: archive_message(
                102,
                photo=True,
                text="الفيلم: Resume\nالسنة: 2025\nالقصة: قصة",
            ),
            103: archive_message(
                103,
                video=True,
                text="Resume 2025 #720p",
            ),
        }
    )
    service = HistoricalImportService(
        database=database,
        gateway=gateway,  # type: ignore[arg-type]
        reindex_batch_size=10,
    )

    completed = await service.reindex(job_id=job_id, full=False)

    assert completed.last_reindexed_source_message_id == 3
    assert gateway.requested_batches == [(102, 103)]


@pytest.mark.asyncio
async def test_missing_archive_message_is_counted_and_does_not_block(
    database: Database,
) -> None:
    job_id = await seed_job_and_mappings(database)
    gateway = ReindexGateway(
        {
            101: archive_message(
                101,
                photo=True,
                text="الفيلم: Missing Test\nالسنة: 2025\nالقصة: قصة",
            ),
            102: None,
            103: archive_message(
                103,
                video=True,
                text="Missing Test 2025 #720p",
            ),
        }
    )
    service = HistoricalImportService(
        database=database,
        gateway=gateway,  # type: ignore[arg-type]
    )

    completed = await service.reindex(job_id=job_id, full=False)

    assert completed.status == "completed"
    assert completed.missing_archive_messages == 1
    assert completed.reindexed_messages == 2


@pytest.mark.asyncio
async def test_full_replay_is_idempotent_and_does_not_double_count(
    database: Database,
) -> None:
    job_id = await seed_job_and_mappings(database)
    gateway = ReindexGateway(
        {
            101: archive_message(
                101,
                photo=True,
                text="الفيلم: Replay\nالسنة: 2025\nالقصة: قصة",
            ),
            102: archive_message(
                102,
                video=True,
                text="Replay 2025 #720p",
            ),
            103: archive_message(
                103,
                video=True,
                text="Replay 2025 #1080p",
            ),
        }
    )
    service = HistoricalImportService(
        database=database,
        gateway=gateway,  # type: ignore[arg-type]
    )

    first = await service.reindex(job_id=job_id, full=False)
    second = await service.reindex(job_id=job_id, full=True)

    assert first.reindexed_messages == 3
    assert second.reindexed_messages == 3
    assert second.missing_archive_messages == 0

    async with database.session() as session:
        movie_count = await session.scalar(select(func.count(Movie.id)))
        quality_count = await session.scalar(select(func.count(MovieQuality.id)))

    assert movie_count == 1
    assert quality_count == 2


@pytest.mark.asyncio
async def test_existing_live_index_rows_are_not_duplicated(
    database: Database,
) -> None:
    job_id = await seed_job_and_mappings(database)
    poster = archive_message(
        101,
        photo=True,
        text="الفيلم: Existing\nالسنة: 2025\nالقصة: قصة",
    )
    quality = archive_message(
        102,
        video=True,
        text="Existing 2025 #720p",
    )

    indexer = ArchiveIndexService(database)
    await indexer.ingest(
        channel_id=ARCHIVE_ID,
        message=telethon_message_to_archive(poster),
    )
    await indexer.ingest(
        channel_id=ARCHIVE_ID,
        message=telethon_message_to_archive(quality),
    )

    gateway = ReindexGateway(
        {
            101: poster,
            102: quality,
            103: archive_message(103, text="ordinary noise"),
        }
    )
    service = HistoricalImportService(
        database=database,
        gateway=gateway,  # type: ignore[arg-type]
    )

    await service.reindex(job_id=job_id, full=False)

    async with database.session() as session:
        movie_count = await session.scalar(select(func.count(Movie.id)))
        quality_count = await session.scalar(select(func.count(MovieQuality.id)))

    assert movie_count == 1
    assert quality_count == 1



def forwarded_archive_message(
    archive_message_id: int,
    *,
    source_message_id: int,
    source_channel_id: int = SOURCE_ID,
):
    return SimpleNamespace(
        id=archive_message_id,
        photo=None,
        video=None,
        document=None,
        raw_text="forwarded",
        fwd_from=SimpleNamespace(
            channel_post=source_message_id,
            from_id=None,
        ),
        forward=SimpleNamespace(chat_id=source_channel_id),
    )


@pytest.mark.asyncio
async def test_verify_is_non_destructive_and_reports_missing_and_mismatch(
    database: Database,
) -> None:
    job_id = await seed_job_and_mappings(database)
    gateway = ReindexGateway(
        {
            101: forwarded_archive_message(
                101,
                source_message_id=1,
            ),
            102: None,
            103: forwarded_archive_message(
                103,
                source_message_id=3,
                source_channel_id=-1009999999999,
            ),
        }
    )
    service = HistoricalImportService(
        database=database,
        gateway=gateway,  # type: ignore[arg-type]
        reindex_batch_size=2,
    )

    before = None
    async with database.session() as session:
        before = await ArchiveImportRepository(session).get_job(job_id)

    verification = await service.verify(job_id=job_id)

    async with database.session() as session:
        after = await ArchiveImportRepository(session).get_job(job_id)

    assert verification.total_mappings == 3
    assert verification.present_messages == 1
    assert verification.missing_messages == 1
    assert verification.source_mismatches == 1
    assert before == after
