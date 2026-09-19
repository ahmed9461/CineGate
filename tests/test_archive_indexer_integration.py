from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select

from cinegate.db.models import AppSetting, MessageTemplate, Movie, MovieQuality
from cinegate.db.session import Database
from cinegate.domain.archive import ArchiveMessage, MediaKind
from cinegate.domain.indexing import IndexAction
from cinegate.repositories.settings import SettingsRepository
from cinegate.services.archive_indexer import ArchiveIndexService
from cinegate.services.owner_notifier import OwnerArchiveNotifier

DATABASE_URL = os.getenv("CINEGATE_DATABASE_URL")
ARCHIVE_CHANNEL_ID = -1001234567890


async def clean_database(database: Database) -> None:
    async with database.session() as session, session.begin():
            await session.execute(delete(MovieQuality))
            await session.execute(delete(Movie))
            await session.execute(delete(AppSetting))
            await session.execute(delete(MessageTemplate))


@pytest_asyncio.fixture
async def database() -> Database:
    if not DATABASE_URL:
        pytest.skip("CINEGATE_DATABASE_URL is not configured")

    database = Database(DATABASE_URL, pool_size=2, max_overflow=0)
    await clean_database(database)
    try:
        yield database
    finally:
        await clean_database(database)
        await database.dispose()


async def set_setting(database: Database, key: str, value) -> None:
    async with database.session() as session, session.begin():
            await SettingsRepository(session).set(key, value)


def modern_poster(
    message_id: int,
    *,
    title: str = "Interstellar",
    year: int = 2014,
) -> ArchiveMessage:
    return ArchiveMessage(
        message_id=message_id,
        media_kind=MediaKind.PHOTO,
        caption=(
            f"الفيلم: {title}\n"
            "التصنيف: خيال علمي\n"
            "اللغة: الإنجليزية\n"
            f"السنة: {year}\n"
            "القصة: قصة"
        ),
    )


def quality(
    message_id: int,
    *,
    title: str = "Interstellar",
    year: int = 2014,
    resolution: str = "720p",
) -> ArchiveMessage:
    return ArchiveMessage(
        message_id=message_id,
        media_kind=MediaKind.VIDEO,
        caption=f"{title} {year} #{resolution}",
    )


@pytest.mark.asyncio
async def test_settings_repository_missing_and_idempotent_upsert(database: Database) -> None:
    async with database.session() as session, session.begin():
            repository = SettingsRepository(session)
            assert await repository.get_int("archive_channel_id") is None

            await repository.set("archive_channel_id", ARCHIVE_CHANNEL_ID)
            assert await repository.get_int("archive_channel_id") == ARCHIVE_CHANNEL_ID

            await repository.set("archive_channel_id", ARCHIVE_CHANNEL_ID)
            assert await repository.get_int("archive_channel_id") == ARCHIVE_CHANNEL_ID


@pytest.mark.asyncio
async def test_poster_and_qualities_are_persisted_idempotently(database: Database) -> None:
    await set_setting(database, "archive_channel_id", ARCHIVE_CHANNEL_ID)
    indexer = ArchiveIndexService(database)

    poster_result = await indexer.ingest(
        channel_id=ARCHIVE_CHANNEL_ID,
        message=modern_poster(100),
    )
    assert poster_result.action is IndexAction.POSTER_UPSERTED

    first = await indexer.ingest(
        channel_id=ARCHIVE_CHANNEL_ID,
        message=quality(101),
    )
    assert first.action is IndexAction.QUALITY_UPSERTED
    assert first.quality_count == 1

    duplicate = await indexer.ingest(
        channel_id=ARCHIVE_CHANNEL_ID,
        message=quality(101),
    )
    assert duplicate.action is IndexAction.DUPLICATE
    assert duplicate.quality_count == 1

    replacement = await indexer.ingest(
        channel_id=ARCHIVE_CHANNEL_ID,
        message=quality(102),
    )
    assert replacement.action is IndexAction.QUALITY_UPSERTED
    assert replacement.quality_count == 1

    second_quality = await indexer.ingest(
        channel_id=ARCHIVE_CHANNEL_ID,
        message=quality(103, resolution="1080p"),
    )
    assert second_quality.action is IndexAction.QUALITY_UPSERTED
    assert second_quality.quality_count == 2

    async with database.session() as session:
        movie = await session.scalar(select(Movie))
        assert movie is not None
        assert movie.status == "indexed"

        rows = (
            await session.execute(
                select(MovieQuality).order_by(MovieQuality.quality)
            )
        ).scalars().all()
        assert len(rows) == 2
        by_quality = {row.quality: row for row in rows}
        assert by_quality["720p"].archive_message_id == 102
        assert by_quality["1080p"].archive_message_id == 103


@pytest.mark.asyncio
async def test_duplicate_poster_does_not_create_duplicate_movie(database: Database) -> None:
    await set_setting(database, "archive_channel_id", ARCHIVE_CHANNEL_ID)
    indexer = ArchiveIndexService(database)

    await indexer.ingest(channel_id=ARCHIVE_CHANNEL_ID, message=modern_poster(100))
    await indexer.ingest(channel_id=ARCHIVE_CHANNEL_ID, message=modern_poster(100))

    async with database.session() as session:
        count = await session.scalar(select(func.count(Movie.id)))
        assert count == 1


@pytest.mark.asyncio
async def test_pending_poster_becomes_orphan_when_next_poster_arrives(
    database: Database,
) -> None:
    await set_setting(database, "archive_channel_id", ARCHIVE_CHANNEL_ID)
    indexer = ArchiveIndexService(database)

    await indexer.ingest(
        channel_id=ARCHIVE_CHANNEL_ID,
        message=modern_poster(100, title="No Quality", year=2020),
    )
    await indexer.ingest(
        channel_id=ARCHIVE_CHANNEL_ID,
        message=modern_poster(200, title="Next Movie", year=2021),
    )

    async with database.session() as session:
        movies = (
            await session.execute(select(Movie).order_by(Movie.poster_message_id))
        ).scalars().all()

    assert [movie.status for movie in movies] == ["orphan", "pending"]


@pytest.mark.asyncio
async def test_cross_language_quality_attaches_but_conflicting_year_does_not(
    database: Database,
) -> None:
    await set_setting(database, "archive_channel_id", ARCHIVE_CHANNEL_ID)
    indexer = ArchiveIndexService(database)

    await indexer.ingest(
        channel_id=ARCHIVE_CHANNEL_ID,
        message=modern_poster(
            100,
            title="La sociedad de la nieve",
            year=2023,
        ),
    )

    accepted = await indexer.ingest(
        channel_id=ARCHIVE_CHANNEL_ID,
        message=quality(
            101,
            title="Society of the Snow",
            year=2023,
        ),
    )
    assert accepted.action is IndexAction.QUALITY_UPSERTED

    ambiguous = await indexer.ingest(
        channel_id=ARCHIVE_CHANNEL_ID,
        message=quality(
            102,
            title="La sociedad de la nieve",
            year=2022,
            resolution="1080p",
        ),
    )
    assert ambiguous.action is IndexAction.AMBIGUOUS

    async with database.session() as session:
        count = await session.scalar(select(func.count(MovieQuality.id)))
        assert count == 1


@pytest.mark.asyncio
async def test_wrong_channel_and_quality_without_poster_are_ignored(
    database: Database,
) -> None:
    await set_setting(database, "archive_channel_id", ARCHIVE_CHANNEL_ID)
    indexer = ArchiveIndexService(database)

    wrong_channel = await indexer.ingest(
        channel_id=-999,
        message=modern_poster(100),
    )
    no_poster = await indexer.ingest(
        channel_id=ARCHIVE_CHANNEL_ID,
        message=quality(101),
    )

    assert wrong_channel.action is IndexAction.IGNORED
    assert no_poster.action is IndexAction.IGNORED


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []
        self.edited: list[tuple[int, int, str]] = []
        self.deleted: list[tuple[int, int]] = []
        self._next_message_id = 500

    async def send_message(self, chat_id: int, text: str):
        self.sent.append((chat_id, text))
        message_id = self._next_message_id
        self._next_message_id += 1
        return SimpleNamespace(message_id=message_id)

    async def edit_message_text(self, *, chat_id: int, message_id: int, text: str):
        self.edited.append((chat_id, message_id, text))

    async def delete_message(self, *, chat_id: int, message_id: int):
        self.deleted.append((chat_id, message_id))


@pytest.mark.asyncio
async def test_owner_notification_is_sent_once_then_edited(database: Database) -> None:
    await set_setting(database, "archive_channel_id", ARCHIVE_CHANNEL_ID)
    await set_setting(database, "owner_chat_id", 777)

    indexer = ArchiveIndexService(database)
    await indexer.ingest(channel_id=ARCHIVE_CHANNEL_ID, message=modern_poster(100))
    first = await indexer.ingest(
        channel_id=ARCHIVE_CHANNEL_ID,
        message=quality(101),
    )
    assert first.movie_id is not None

    bot = FakeBot()
    notifier = OwnerArchiveNotifier(database, bot)  # type: ignore[arg-type]
    await notifier.notify_movie(first.movie_id)

    assert bot.sent == [(777, "✅ تم حفظ منشورات جديدة\n\n1- Interstellar (1)")]

    second = await indexer.ingest(
        channel_id=ARCHIVE_CHANNEL_ID,
        message=quality(102, resolution="1080p"),
    )
    assert second.movie_id == first.movie_id
    await notifier.notify_movie(second.movie_id)

    assert bot.edited[-1] == (
        777,
        500,
        "✅ تم حفظ منشورات جديدة\n\n1- Interstellar (2)",
    )

    async with database.session() as session:
        notification_id = await session.scalar(
            select(Movie.owner_notification_message_id).where(Movie.id == first.movie_id)
        )
    assert notification_id == 500
