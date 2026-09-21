from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select

from cinegate.db.models import AppSetting, Movie, MovieQuality
from cinegate.db.session import Database
from cinegate.repositories.settings import SettingsRepository
from cinegate.services.archive_integrity import ArchiveIntegrityAuditService

DATABASE_URL = os.getenv("CINEGATE_DATABASE_URL")
ARCHIVE_ID = -1002222222222


class FakeGateway:
    def __init__(self, missing_ids: set[int]) -> None:
        self.archive = object()
        self.missing_ids = missing_ids
        self.batches: list[tuple[int, ...]] = []

    async def resolve_channel(self, channel_id: int):
        assert channel_id == ARCHIVE_ID
        return self.archive

    async def get_messages_by_ids(self, entity, message_ids):
        assert entity is self.archive
        ids = tuple(int(value) for value in message_ids)
        self.batches.append(ids)
        return tuple(
            None if message_id in self.missing_ids else SimpleNamespace(id=message_id)
            for message_id in ids
        )


async def clean(database: Database) -> None:
    async with database.session() as session, session.begin():
        await session.execute(delete(MovieQuality))
        await session.execute(delete(Movie))
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


async def seed_movie(
    database: Database,
    *,
    poster_message_id: int,
    status: str,
    qualities: tuple[tuple[int, str], ...],
) -> int:
    async with database.session() as session, session.begin():
        movie = Movie(
            archive_channel_id=ARCHIVE_ID,
            poster_message_id=poster_message_id,
            display_title=f"Movie {poster_message_id}",
            normalized_title=f"movie {poster_message_id}",
            year=2025,
            parser_style="modern",
            status=status,
            raw_poster_caption=f"الفيلم: Movie {poster_message_id}",
            parser_confidence=95,
        )
        session.add(movie)
        await session.flush()

        for message_id, quality in qualities:
            session.add(
                MovieQuality(
                    movie_id=movie.id,
                    archive_channel_id=ARCHIVE_ID,
                    archive_message_id=message_id,
                    quality=quality,
                    raw_caption=f"Movie 2025 #{quality}",
                    extracted_title="Movie",
                    normalized_title="movie",
                    extracted_year=2025,
                    parser_confidence=95,
                )
            )

        await session.flush()
        return movie.id


@pytest.mark.asyncio
async def test_integrity_audit_reports_missing_indexed_references_read_only(
    database: Database,
) -> None:
    async with database.session() as session, session.begin():
        await SettingsRepository(session).set("archive_channel_id", ARCHIVE_ID)

    indexed_id = await seed_movie(
        database,
        poster_message_id=100,
        status="indexed",
        qualities=((101, "720p"), (102, "1080p")),
    )
    await seed_movie(
        database,
        poster_message_id=200,
        status="ambiguous",
        qualities=((201, "720p"),),
    )

    gateway = FakeGateway({100, 102, 200, 201})
    service = ArchiveIntegrityAuditService(
        database=database,
        gateway=gateway,  # type: ignore[arg-type]
        batch_size=1,
    )

    before_counts = None
    async with database.session() as session:
        before_counts = (
            await session.scalar(select(func.count(Movie.id))),
            await session.scalar(select(func.count(MovieQuality.id))),
        )

    report = await service.verify()

    async with database.session() as session:
        after_counts = (
            await session.scalar(select(func.count(Movie.id))),
            await session.scalar(select(func.count(MovieQuality.id))),
        )
        movie = await session.get(Movie, indexed_id)

    assert report.checked_posters == 1
    assert report.checked_qualities == 2
    assert report.missing_posters == 1
    assert report.missing_qualities == 1
    assert not report.ok
    assert {(item.kind, item.archive_message_id) for item in report.missing_examples} == {
        ("poster", 100),
        ("quality", 102),
    }
    assert before_counts == after_counts
    assert movie is not None
    assert movie.status == "indexed"

    # Batch size=1 is honored for both poster and quality lookups.
    assert all(len(batch) == 1 for batch in gateway.batches)
    assert (200,) not in gateway.batches
    assert (201,) not in gateway.batches


@pytest.mark.asyncio
async def test_integrity_audit_is_ok_when_all_indexed_references_exist(
    database: Database,
) -> None:
    async with database.session() as session, session.begin():
        await SettingsRepository(session).set("archive_channel_id", ARCHIVE_ID)

    await seed_movie(
        database,
        poster_message_id=300,
        status="indexed",
        qualities=((301, "720p"),),
    )

    report = await ArchiveIntegrityAuditService(
        database=database,
        gateway=FakeGateway(set()),  # type: ignore[arg-type]
    ).verify()

    assert report.ok
    assert report.missing_posters == 0
    assert report.missing_qualities == 0



@pytest.mark.asyncio
async def test_integrity_audit_treats_non_importable_telegram_result_as_missing(
    database: Database,
) -> None:
    async with database.session() as session, session.begin():
        await SettingsRepository(session).set("archive_channel_id", ARCHIVE_ID)

    await seed_movie(
        database,
        poster_message_id=400,
        status="indexed",
        qualities=((401, "720p"),),
    )

    class EmptyResultGateway(FakeGateway):
        async def get_messages_by_ids(self, entity, message_ids):
            ids = tuple(int(value) for value in message_ids)
            self.batches.append(ids)
            return tuple(
                SimpleNamespace(id=0)
                if message_id == 401
                else SimpleNamespace(id=message_id)
                for message_id in ids
            )

    report = await ArchiveIntegrityAuditService(
        database=database,
        gateway=EmptyResultGateway(set()),  # type: ignore[arg-type]
    ).verify()

    assert report.checked_posters == 1
    assert report.checked_qualities == 1
    assert report.missing_posters == 0
    assert report.missing_qualities == 1
