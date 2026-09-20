from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import delete

from cinegate.db.models import (
    AppSetting,
    ArchiveImportJob,
    ArchiveImportMessageMap,
)
from cinegate.db.session import Database
from cinegate.importer.errors import (
    HistoricalImportError,
    ImportChannelAccessError,
    ImportFloodWaitTooLong,
    SourceForwardingRestricted,
)
from cinegate.importer.service import HistoricalImportService
from cinegate.repositories.import_jobs import ArchiveImportRepository

DATABASE_URL = os.getenv("CINEGATE_DATABASE_URL")
SOURCE_ID = -1001111111111
ARCHIVE_ID = -1002222222222


def source_message(
    message_id: int,
    *,
    photo=False,
    video=False,
    text: str | None = None,
    service=False,
):
    return SimpleNamespace(
        id=message_id,
        photo=object() if photo else None,
        video=object() if video else None,
        document=None,
        raw_text=text,
        fwd_from=None,
        forward=None,
        service=service,
    )


class FakeGateway:
    def __init__(self, messages) -> None:
        self.source = object()
        self.archive = object()
        self.source_messages = list(messages)
        self.archive_messages: dict[int, object] = {}
        self.next_archive_id = 101
        self.forward_batches: list[tuple[int, ...]] = []
        self.fail_after_store_once = False
        self.protected = False
        self.permission_denied = False
        self.flood_seconds: int | None = None

    async def resolve_channels(self, *, source_channel_id, archive_channel_id):
        assert source_channel_id == SOURCE_ID
        assert archive_channel_id == ARCHIVE_ID
        if self.protected:
            raise SourceForwardingRestricted("source protection enabled")
        return self.source, self.archive

    async def resolve_channel(self, channel_id):
        assert channel_id == ARCHIVE_ID
        return self.archive

    async def latest_message_id(self, entity):
        if entity is self.source:
            return max((message.id for message in self.source_messages), default=0)
        return max(self.archive_messages, default=100)

    async def total_message_estimate(self, entity):
        assert entity is self.source
        return len(self.source_messages)

    async def iter_source_messages(
        self,
        entity,
        *,
        after_message_id,
        high_watermark_id,
    ):
        assert entity is self.source
        for message in self.source_messages:
            if after_message_id < message.id <= high_watermark_id:
                yield message

    async def iter_archive_messages_after(self, entity, *, after_message_id):
        assert entity is self.archive
        for message_id in sorted(self.archive_messages):
            if message_id > after_message_id:
                yield self.archive_messages[message_id]

    async def forward_batch(self, *, source, archive, messages):
        assert source is self.source
        assert archive is self.archive
        if self.permission_denied:
            raise ImportChannelAccessError("cannot write to archive")
        if self.flood_seconds is not None:
            raise ImportFloodWaitTooLong(self.flood_seconds)

        self.forward_batches.append(tuple(message.id for message in messages))
        forwarded = []
        for original in messages:
            archive_message = SimpleNamespace(
                id=self.next_archive_id,
                photo=original.photo,
                video=original.video,
                document=original.document,
                raw_text=original.raw_text,
                fwd_from=SimpleNamespace(
                    channel_post=original.id,
                    from_id=None,
                ),
                forward=SimpleNamespace(chat_id=SOURCE_ID),
            )
            self.archive_messages[self.next_archive_id] = archive_message
            forwarded.append(archive_message)
            self.next_archive_id += 1

        if self.fail_after_store_once:
            self.fail_after_store_once = False
            raise HistoricalImportError(
                "simulated crash after Telegram accepted forward"
            )

        return tuple(forwarded)

    async def get_messages_by_ids(self, entity, message_ids):
        assert entity is self.archive
        return tuple(self.archive_messages.get(value) for value in message_ids)


async def clean(database: Database) -> None:
    async with database.session() as session, session.begin():
        await session.execute(delete(ArchiveImportMessageMap))
        await session.execute(delete(ArchiveImportJob))
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


@pytest.mark.asyncio
async def test_transfer_is_oldest_first_bounded_and_resumable(
    database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages = [
        source_message(1, photo=True, text="الفيلم: Test\nالسنة: 2025"),
        source_message(2, video=True, text="Test 2025 #720p"),
        source_message(3, service=True),
        source_message(4, video=True, text="noise #1080p"),
        source_message(5, text="ordinary text"),
    ]
    gateway = FakeGateway(messages)
    monkeypatch.setattr(
        "cinegate.importer.service.is_importable_message",
        lambda message: not message.service,
    )
    progress = []

    async def report(job):
        progress.append((job.status, job.processed_messages))

    service = HistoricalImportService(
        database=database,
        gateway=gateway,  # type: ignore[arg-type]
        batch_size=2,
        progress_callback=report,
    )

    job = await service.transfer(
        source_channel_id=SOURCE_ID,
        archive_channel_id=ARCHIVE_ID,
    )

    assert job.status == "transferred"
    assert gateway.forward_batches == [(1, 2), (4,), (5,)]
    assert all(len(batch) <= 2 for batch in gateway.forward_batches)
    assert job.last_copied_source_message_id == 5
    assert job.processed_messages == 5
    assert job.skipped_messages == 1
    assert job.copied_messages == 4
    assert progress[0][0] == "running"
    assert progress[-1][0] == "transferred"

    second = await service.transfer(
        source_channel_id=SOURCE_ID,
        archive_channel_id=ARCHIVE_ID,
    )

    assert second.copied_messages == 4
    assert gateway.forward_batches == [(1, 2), (4,), (5,)]


@pytest.mark.asyncio
async def test_crash_after_forward_is_reconciled_without_duplicate(
    database: Database,
) -> None:
    gateway = FakeGateway(
        [
            source_message(1, photo=True, text="الفيلم: Test\nالسنة: 2025"),
            source_message(2, video=True, text="Test 2025 #720p"),
        ]
    )
    gateway.fail_after_store_once = True
    service = HistoricalImportService(
        database=database,
        gateway=gateway,  # type: ignore[arg-type]
        batch_size=2,
    )

    with pytest.raises(HistoricalImportError):
        await service.transfer(
            source_channel_id=SOURCE_ID,
            archive_channel_id=ARCHIVE_ID,
        )

    async with database.session() as session:
        repository = ArchiveImportRepository(session)
        job = await repository.get_job_by_pair(
            source_channel_id=SOURCE_ID,
            archive_channel_id=ARCHIVE_ID,
        )
        assert job is not None
        assert await repository.count_mappings(job.id) == 0

    resumed = await service.transfer(
        source_channel_id=SOURCE_ID,
        archive_channel_id=ARCHIVE_ID,
    )

    assert resumed.status == "transferred"
    assert resumed.reconciled_messages == 2
    assert resumed.copied_messages == 2
    assert len(gateway.forward_batches) == 1

    async with database.session() as session:
        repository = ArchiveImportRepository(session)
        assert await repository.count_mappings(resumed.id) == 2


@pytest.mark.asyncio
async def test_protected_source_is_refused_before_forward(database: Database) -> None:
    gateway = FakeGateway([source_message(1, text="x")])
    gateway.protected = True
    service = HistoricalImportService(
        database=database,
        gateway=gateway,  # type: ignore[arg-type]
    )

    with pytest.raises(SourceForwardingRestricted):
        await service.transfer(
            source_channel_id=SOURCE_ID,
            archive_channel_id=ARCHIVE_ID,
        )

    assert gateway.forward_batches == []


@pytest.mark.asyncio
async def test_excessive_flood_wait_pauses_job(database: Database) -> None:
    gateway = FakeGateway([source_message(1, text="x")])
    gateway.flood_seconds = 601
    service = HistoricalImportService(
        database=database,
        gateway=gateway,  # type: ignore[arg-type]
    )

    with pytest.raises(ImportFloodWaitTooLong):
        await service.transfer(
            source_channel_id=SOURCE_ID,
            archive_channel_id=ARCHIVE_ID,
        )

    async with database.session() as session:
        repository = ArchiveImportRepository(session)
        job = await repository.get_job_by_pair(
            source_channel_id=SOURCE_ID,
            archive_channel_id=ARCHIVE_ID,
        )

    assert job is not None
    assert job.status == "paused"
    assert "601" in (job.last_error or "")


@pytest.mark.asyncio
async def test_large_history_never_exceeds_configured_forward_batch(
    database: Database,
) -> None:
    gateway = FakeGateway(
        [source_message(index, text=f"message {index}") for index in range(1, 251)]
    )
    service = HistoricalImportService(
        database=database,
        gateway=gateway,  # type: ignore[arg-type]
        batch_size=25,
    )

    job = await service.transfer(
        source_channel_id=SOURCE_ID,
        archive_channel_id=ARCHIVE_ID,
    )

    assert job.processed_messages == 250
    assert job.copied_messages == 250
    assert len(gateway.forward_batches) == 10
    assert max(len(batch) for batch in gateway.forward_batches) == 25



@pytest.mark.asyncio
async def test_write_permission_failure_does_not_advance_checkpoint(
    database: Database,
) -> None:
    gateway = FakeGateway(
        [
            source_message(1, text="one"),
            source_message(2, text="two"),
        ]
    )
    gateway.permission_denied = True
    service = HistoricalImportService(
        database=database,
        gateway=gateway,  # type: ignore[arg-type]
        batch_size=2,
    )

    with pytest.raises(ImportChannelAccessError):
        await service.transfer(
            source_channel_id=SOURCE_ID,
            archive_channel_id=ARCHIVE_ID,
        )

    async with database.session() as session:
        repository = ArchiveImportRepository(session)
        job = await repository.get_job_by_pair(
            source_channel_id=SOURCE_ID,
            archive_channel_id=ARCHIVE_ID,
        )
        assert job is not None
        mapping_count = await repository.count_mappings(job.id)

    assert job.status == "failed"
    assert job.last_copied_source_message_id == 0
    assert job.processed_messages == 0
    assert job.copied_messages == 0
    assert mapping_count == 0



@pytest.mark.asyncio
async def test_transfer_is_rejected_while_reindex_is_active(
    database: Database,
) -> None:
    gateway = FakeGateway([source_message(1, text="one")])

    async with database.session() as session, session.begin():
        repository = ArchiveImportRepository(session)
        job = await repository.get_or_create_job(
            source_channel_id=SOURCE_ID,
            archive_channel_id=ARCHIVE_ID,
        )
        await repository.initialize_snapshot(
            job_id=job.id,
            source_high_watermark_id=1,
            archive_baseline_message_id=100,
            source_total_estimate=1,
        )
        await repository.record_transfer_batch(
            job_id=job.id,
            processed_through_source_id=1,
            processed_count=1,
            skipped_count=0,
            forwarded_mappings=((1, 101),),
        )
        await repository.mark_running(job.id)
        await repository.mark_transferred(job.id)
        await repository.mark_reindexing(job.id)

    service = HistoricalImportService(
        database=database,
        gateway=gateway,  # type: ignore[arg-type]
    )

    with pytest.raises(HistoricalImportError, match="reindex is active"):
        await service.transfer(
            source_channel_id=SOURCE_ID,
            archive_channel_id=ARCHIVE_ID,
        )

    assert gateway.forward_batches == []



@pytest.mark.asyncio
async def test_snapshot_high_watermark_excludes_newer_source_messages(
    database: Database,
) -> None:
    gateway = FakeGateway(
        [
            source_message(1, text="one"),
            source_message(2, text="two"),
            source_message(3, text="arrived later"),
        ]
    )

    async with database.session() as session, session.begin():
        repository = ArchiveImportRepository(session)
        job = await repository.get_or_create_job(
            source_channel_id=SOURCE_ID,
            archive_channel_id=ARCHIVE_ID,
        )
        await repository.initialize_snapshot(
            job_id=job.id,
            source_high_watermark_id=2,
            archive_baseline_message_id=100,
            source_total_estimate=2,
        )

    service = HistoricalImportService(
        database=database,
        gateway=gateway,  # type: ignore[arg-type]
        batch_size=10,
    )

    transferred = await service.transfer(
        source_channel_id=SOURCE_ID,
        archive_channel_id=ARCHIVE_ID,
    )

    assert transferred.source_high_watermark_id == 2
    assert transferred.last_copied_source_message_id == 2
    assert gateway.forward_batches == [(1, 2)]


@pytest.mark.asyncio
async def test_nonmonotonic_destination_ids_pause_without_checkpoint(
    database: Database,
) -> None:
    class NonMonotonicGateway(FakeGateway):
        async def forward_batch(self, *, source, archive, messages):
            self.forward_batches.append(tuple(message.id for message in messages))
            return (
                SimpleNamespace(id=102),
                SimpleNamespace(id=101),
            )

    gateway = NonMonotonicGateway(
        [
            source_message(1, text="one"),
            source_message(2, text="two"),
        ]
    )
    service = HistoricalImportService(
        database=database,
        gateway=gateway,  # type: ignore[arg-type]
        batch_size=2,
    )

    with pytest.raises(HistoricalImportError, match="strictly increasing"):
        await service.transfer(
            source_channel_id=SOURCE_ID,
            archive_channel_id=ARCHIVE_ID,
        )

    async with database.session() as session:
        repository = ArchiveImportRepository(session)
        job = await repository.get_job_by_pair(
            source_channel_id=SOURCE_ID,
            archive_channel_id=ARCHIVE_ID,
        )
        assert job is not None
        mapping_count = await repository.count_mappings(job.id)

    assert job.status == "paused"
    assert job.last_copied_source_message_id == 0
    assert mapping_count == 0



@pytest.mark.asyncio
async def test_progress_failure_does_not_abort_historical_transfer(
    database: Database,
) -> None:
    gateway = FakeGateway(
        [
            source_message(1, text="one"),
            source_message(2, text="two"),
        ]
    )

    async def broken_progress(job):
        raise RuntimeError("progress channel unavailable")

    service = HistoricalImportService(
        database=database,
        gateway=gateway,  # type: ignore[arg-type]
        batch_size=2,
        progress_callback=broken_progress,
    )

    job = await service.transfer(
        source_channel_id=SOURCE_ID,
        archive_channel_id=ARCHIVE_ID,
    )

    assert job.status == "transferred"
    assert job.copied_messages == 2
    assert gateway.forward_batches == [(1, 2)]
