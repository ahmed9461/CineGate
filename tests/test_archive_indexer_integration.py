from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select

from cinegate.db.models import (
    AppSetting,
    Delivery,
    MessageTemplate,
    Movie,
    MovieQuality,
    RewardSession,
    UserSearchSession,
)
from cinegate.db.session import Database
from cinegate.domain.archive import ArchiveMessage, MediaKind
from cinegate.domain.indexing import IndexAction
from cinegate.repositories.settings import SettingsRepository
from cinegate.services.archive_indexer import ArchiveIndexService
from cinegate.services.movie_search import MovieSearchService
from cinegate.services.owner_notifier import OwnerArchiveNotifier

DATABASE_URL = os.getenv("CINEGATE_DATABASE_URL")
ARCHIVE_CHANNEL_ID = -1001234567890


async def clean_database(database: Database) -> None:
    async with database.session() as session, session.begin():
        await session.execute(delete(Delivery))
        await session.execute(delete(RewardSession))
        await session.execute(delete(UserSearchSession))
        await session.execute(delete(MovieQuality))
        await session.execute(delete(Movie))
        await session.execute(delete(AppSetting))
        await session.execute(delete(MessageTemplate))


@pytest_asyncio.fixture
async def database() -> Database:
    if not DATABASE_URL:
        pytest.skip("CINEGATE_DATABASE_URL is not configured")

    database = Database(DATABASE_URL, pool_size=4, max_overflow=0)
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
            await session.execute(select(MovieQuality).order_by(MovieQuality.quality))
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


@pytest.mark.asyncio
async def test_rapid_parallel_qualities_are_serialized_per_movie(
    database: Database,
) -> None:
    await set_setting(database, "archive_channel_id", ARCHIVE_CHANNEL_ID)
    indexer = ArchiveIndexService(database)
    await indexer.ingest(channel_id=ARCHIVE_CHANNEL_ID, message=modern_poster(100))

    results = await asyncio.gather(
        indexer.ingest(
            channel_id=ARCHIVE_CHANNEL_ID,
            message=quality(101, resolution="720p"),
        ),
        indexer.ingest(
            channel_id=ARCHIVE_CHANNEL_ID,
            message=quality(102, resolution="1080p"),
        ),
    )

    assert {result.action for result in results} == {IndexAction.QUALITY_UPSERTED}

    async with database.session() as session:
        rows = (
            await session.execute(
                select(MovieQuality).order_by(MovieQuality.archive_message_id)
            )
        ).scalars().all()

    assert [(row.archive_message_id, row.quality) for row in rows] == [
        (101, "720p"),
        (102, "1080p"),
    ]


@pytest.mark.asyncio
async def test_rapid_duplicate_quality_does_not_duplicate_row(database: Database) -> None:
    await set_setting(database, "archive_channel_id", ARCHIVE_CHANNEL_ID)
    indexer = ArchiveIndexService(database)
    await indexer.ingest(channel_id=ARCHIVE_CHANNEL_ID, message=modern_poster(100))

    first, second = await asyncio.gather(
        indexer.ingest(channel_id=ARCHIVE_CHANNEL_ID, message=quality(101)),
        indexer.ingest(channel_id=ARCHIVE_CHANNEL_ID, message=quality(101)),
    )

    assert {first.action, second.action} == {
        IndexAction.QUALITY_UPSERTED,
        IndexAction.DUPLICATE,
    }

    async with database.session() as session:
        count = await session.scalar(select(func.count(MovieQuality.id)))
    assert count == 1


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
        row = (
            await session.execute(
                select(
                    Movie.owner_notification_message_id,
                    Movie.owner_notification_quality_count,
                ).where(Movie.id == first.movie_id)
            )
        ).one()

    assert row.owner_notification_message_id == 500
    assert row.owner_notification_quality_count == 2


@pytest.mark.asyncio
async def test_duplicate_update_retries_notice_until_notification_is_recorded(
    database: Database,
) -> None:
    await set_setting(database, "archive_channel_id", ARCHIVE_CHANNEL_ID)
    await set_setting(database, "owner_chat_id", 777)

    indexer = ArchiveIndexService(database)
    await indexer.ingest(channel_id=ARCHIVE_CHANNEL_ID, message=modern_poster(100))

    first = await indexer.ingest(
        channel_id=ARCHIVE_CHANNEL_ID,
        message=quality(101),
    )
    assert first.action is IndexAction.QUALITY_UPSERTED
    assert first.should_notify_owner

    # Simulate Telegram notification failure by not calling the notifier.
    duplicate_before_notice = await indexer.ingest(
        channel_id=ARCHIVE_CHANNEL_ID,
        message=quality(101),
    )
    assert duplicate_before_notice.action is IndexAction.DUPLICATE
    assert duplicate_before_notice.should_notify_owner
    assert duplicate_before_notice.movie_id is not None

    bot = FakeBot()
    notifier = OwnerArchiveNotifier(database, bot)  # type: ignore[arg-type]
    await notifier.notify_movie(duplicate_before_notice.movie_id)

    duplicate_after_notice = await indexer.ingest(
        channel_id=ARCHIVE_CHANNEL_ID,
        message=quality(101),
    )
    assert duplicate_after_notice.action is IndexAction.DUPLICATE
    assert not duplicate_after_notice.should_notify_owner

    await notifier.notify_movie(duplicate_before_notice.movie_id)
    assert len(bot.sent) == 1
    assert bot.edited == []



class BlockingFirstSendBot(FakeBot):
    def __init__(self) -> None:
        super().__init__()
        self.first_send_started = asyncio.Event()
        self.second_send_started = asyncio.Event()
        self.release_first_send = asyncio.Event()
        self.messages: dict[int, str] = {}

    async def send_message(self, chat_id: int, text: str):
        message_id = self._next_message_id
        self._next_message_id += 1
        self.sent.append((chat_id, text))
        self.messages[message_id] = text

        if len(self.sent) == 1:
            self.first_send_started.set()
            await self.release_first_send.wait()
        elif len(self.sent) == 2:
            self.second_send_started.set()

        return SimpleNamespace(message_id=message_id)

    async def edit_message_text(self, *, chat_id: int, message_id: int, text: str):
        await super().edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
        )
        self.messages[message_id] = text

    async def delete_message(self, *, chat_id: int, message_id: int):
        await super().delete_message(chat_id=chat_id, message_id=message_id)
        self.messages.pop(message_id, None)


@pytest.mark.asyncio
async def test_concurrent_owner_notifiers_converge_to_latest_quality_count(
    database: Database,
) -> None:
    await set_setting(database, "archive_channel_id", ARCHIVE_CHANNEL_ID)
    await set_setting(database, "owner_chat_id", 777)

    indexer = ArchiveIndexService(database)
    await indexer.ingest(channel_id=ARCHIVE_CHANNEL_ID, message=modern_poster(100))
    first = await indexer.ingest(
        channel_id=ARCHIVE_CHANNEL_ID,
        message=quality(101, resolution="720p"),
    )
    assert first.movie_id is not None

    bot = BlockingFirstSendBot()
    notifier = OwnerArchiveNotifier(database, bot)  # type: ignore[arg-type]

    first_notice = asyncio.create_task(notifier.notify_movie(first.movie_id))
    await bot.first_send_started.wait()

    second = await indexer.ingest(
        channel_id=ARCHIVE_CHANNEL_ID,
        message=quality(102, resolution="1080p"),
    )
    assert second.quality_count == 2

    second_notice = asyncio.create_task(notifier.notify_movie(first.movie_id))
    await bot.second_send_started.wait()
    bot.release_first_send.set()

    await asyncio.gather(first_notice, second_notice)

    async with database.session() as session:
        row = (
            await session.execute(
                select(
                    Movie.owner_notification_message_id,
                    Movie.owner_notification_quality_count,
                ).where(Movie.id == first.movie_id)
            )
        ).one()

    assert row.owner_notification_message_id is not None
    assert row.owner_notification_quality_count == 2
    assert bot.messages[row.owner_notification_message_id] == (
        "✅ تم حفظ منشورات جديدة\n\n1- Interstellar (2)"
    )



@pytest.mark.asyncio
async def test_edited_poster_updates_existing_movie_and_keeps_it_indexed(
    database: Database,
) -> None:
    await set_setting(database, "archive_channel_id", ARCHIVE_CHANNEL_ID)
    indexer = ArchiveIndexService(database)

    await indexer.ingest(
        channel_id=ARCHIVE_CHANNEL_ID,
        message=modern_poster(100, title="Original Title", year=2024),
    )
    await indexer.ingest(
        channel_id=ARCHIVE_CHANNEL_ID,
        message=quality(
            101,
            title="Original Title",
            year=2024,
            resolution="720p",
        ),
    )

    result = await indexer.reconcile_edit(
        channel_id=ARCHIVE_CHANNEL_ID,
        message=modern_poster(100, title="Corrected Title", year=2024),
    )

    async with database.session() as session:
        movie = await session.scalar(select(Movie))

    assert result.action is IndexAction.POSTER_UPSERTED
    assert movie is not None
    assert movie.display_title == "Corrected Title"
    assert movie.normalized_title == "corrected title"
    assert movie.status == "indexed"


@pytest.mark.asyncio
async def test_edited_quality_updates_same_archive_message_row(
    database: Database,
) -> None:
    await set_setting(database, "archive_channel_id", ARCHIVE_CHANNEL_ID)
    indexer = ArchiveIndexService(database)

    await indexer.ingest(
        channel_id=ARCHIVE_CHANNEL_ID,
        message=modern_poster(100, title="Sample Feature", year=2025),
    )
    await indexer.ingest(
        channel_id=ARCHIVE_CHANNEL_ID,
        message=quality(
            101,
            title="Sample Feature",
            year=2025,
            resolution="720p",
        ),
    )

    result = await indexer.reconcile_edit(
        channel_id=ARCHIVE_CHANNEL_ID,
        message=quality(
            101,
            title="Sample Feature Corrected",
            year=2025,
            resolution="720p",
        ),
    )

    async with database.session() as session:
        row = await session.scalar(select(MovieQuality))
        movie = await session.scalar(select(Movie))

    assert result.action is IndexAction.QUALITY_UPSERTED
    assert row is not None
    assert row.archive_message_id == 101
    assert row.normalized_title == "sample feature corrected"
    assert movie is not None
    assert movie.status == "indexed"


@pytest.mark.asyncio
async def test_quality_edit_and_new_quality_share_safe_lock_order(
    database: Database,
) -> None:
    await set_setting(database, "archive_channel_id", ARCHIVE_CHANNEL_ID)
    indexer = ArchiveIndexService(database)

    await indexer.ingest(
        channel_id=ARCHIVE_CHANNEL_ID,
        message=modern_poster(100, title="Concurrent Edit", year=2025),
    )
    await indexer.ingest(
        channel_id=ARCHIVE_CHANNEL_ID,
        message=quality(
            101,
            title="Concurrent Edit",
            year=2025,
            resolution="720p",
        ),
    )

    edit_result, ingest_result = await asyncio.wait_for(
        asyncio.gather(
            indexer.reconcile_edit(
                channel_id=ARCHIVE_CHANNEL_ID,
                message=quality(
                    101,
                    title="Concurrent Edit Corrected",
                    year=2025,
                    resolution="720p",
                ),
            ),
            indexer.ingest(
                channel_id=ARCHIVE_CHANNEL_ID,
                message=quality(
                    102,
                    title="Concurrent Edit",
                    year=2025,
                    resolution="1080p",
                ),
            ),
        ),
        timeout=5,
    )

    async with database.session() as session:
        movie = await session.scalar(select(Movie))
        qualities = (
            await session.execute(
                select(MovieQuality).order_by(MovieQuality.archive_message_id)
            )
        ).scalars().all()

    assert edit_result.action is IndexAction.QUALITY_UPSERTED
    assert ingest_result.action is IndexAction.QUALITY_UPSERTED
    assert movie is not None
    assert movie.status == "indexed"
    assert [row.quality for row in qualities] == ["720p", "1080p"]


@pytest.mark.asyncio
async def test_invalid_quality_edit_marks_movie_ambiguous_and_hides_from_search(
    database: Database,
) -> None:
    await set_setting(database, "archive_channel_id", ARCHIVE_CHANNEL_ID)
    indexer = ArchiveIndexService(database)

    await indexer.ingest(
        channel_id=ARCHIVE_CHANNEL_ID,
        message=modern_poster(100, title="Unsafe Edit", year=2025),
    )
    await indexer.ingest(
        channel_id=ARCHIVE_CHANNEL_ID,
        message=quality(
            101,
            title="Unsafe Edit",
            year=2025,
            resolution="720p",
        ),
    )

    result = await indexer.reconcile_edit(
        channel_id=ARCHIVE_CHANNEL_ID,
        message=ArchiveMessage(
            message_id=101,
            media_kind=MediaKind.VIDEO,
            caption="Unsafe Edit 2025",
        ),
    )

    assert result.action is IndexAction.AMBIGUOUS

    async with database.session() as session:
        movie = await session.scalar(select(Movie))
        row = await session.scalar(select(MovieQuality))

    assert movie is not None
    assert movie.status == "ambiguous"
    assert row is not None
    assert row.parser_confidence == 0
    assert row.normalized_title is None

    results = await MovieSearchService(database).search("Unsafe Edit")
    assert results == ()


@pytest.mark.asyncio
async def test_quality_edit_conflicting_with_existing_resolution_is_safe(
    database: Database,
) -> None:
    await set_setting(database, "archive_channel_id", ARCHIVE_CHANNEL_ID)
    indexer = ArchiveIndexService(database)

    await indexer.ingest(
        channel_id=ARCHIVE_CHANNEL_ID,
        message=modern_poster(100, title="Conflict Movie", year=2025),
    )
    await indexer.ingest(
        channel_id=ARCHIVE_CHANNEL_ID,
        message=quality(
            101,
            title="Conflict Movie",
            year=2025,
            resolution="720p",
        ),
    )
    await indexer.ingest(
        channel_id=ARCHIVE_CHANNEL_ID,
        message=quality(
            102,
            title="Conflict Movie",
            year=2025,
            resolution="1080p",
        ),
    )

    result = await indexer.reconcile_edit(
        channel_id=ARCHIVE_CHANNEL_ID,
        message=quality(
            101,
            title="Conflict Movie",
            year=2025,
            resolution="1080p",
        ),
    )

    assert result.action is IndexAction.AMBIGUOUS
    assert result.diagnostic == "edited_quality_conflicts_with_existing_quality"

    async with database.session() as session:
        movie = await session.scalar(select(Movie))
        qualities = (
            await session.execute(
                select(MovieQuality).order_by(MovieQuality.archive_message_id)
            )
        ).scalars().all()

    assert movie is not None
    assert movie.status == "ambiguous"
    assert [(row.archive_message_id, row.quality) for row in qualities] == [
        (101, "720p"),
        (102, "1080p"),
    ]


@pytest.mark.asyncio
async def test_invalid_edit_cannot_be_reactivated_by_stale_or_other_updates(
    database: Database,
) -> None:
    await set_setting(database, "archive_channel_id", ARCHIVE_CHANNEL_ID)
    indexer = ArchiveIndexService(database)

    await indexer.ingest(
        channel_id=ARCHIVE_CHANNEL_ID,
        message=modern_poster(100, title="Stale Update", year=2025),
    )
    await indexer.ingest(
        channel_id=ARCHIVE_CHANNEL_ID,
        message=quality(
            101,
            title="Stale Update",
            year=2025,
            resolution="720p",
        ),
    )
    await indexer.reconcile_edit(
        channel_id=ARCHIVE_CHANNEL_ID,
        message=ArchiveMessage(
            message_id=101,
            media_kind=MediaKind.VIDEO,
            caption="Stale Update 2025",
        ),
    )

    stale = await indexer.ingest(
        channel_id=ARCHIVE_CHANNEL_ID,
        message=quality(
            101,
            title="Stale Update",
            year=2025,
            resolution="720p",
        ),
    )
    other_quality = await indexer.ingest(
        channel_id=ARCHIVE_CHANNEL_ID,
        message=quality(
            102,
            title="Stale Update",
            year=2025,
            resolution="1080p",
        ),
    )
    poster_edit = await indexer.reconcile_edit(
        channel_id=ARCHIVE_CHANNEL_ID,
        message=modern_poster(100, title="Stale Update Corrected", year=2025),
    )

    async with database.session() as session:
        movie = await session.scalar(select(Movie))
        invalid = await session.scalar(
            select(MovieQuality).where(MovieQuality.archive_message_id == 101)
        )

    assert stale.action is IndexAction.AMBIGUOUS
    assert other_quality.action is IndexAction.AMBIGUOUS
    assert poster_edit.action is IndexAction.AMBIGUOUS
    assert not stale.should_notify_owner
    assert not other_quality.should_notify_owner
    assert movie is not None
    assert movie.status == "ambiguous"
    assert invalid is not None
    assert invalid.parser_confidence == 0

    repaired = await indexer.reconcile_edit(
        channel_id=ARCHIVE_CHANNEL_ID,
        message=quality(
            101,
            title="Stale Update Corrected",
            year=2025,
            resolution="720p",
        ),
    )

    async with database.session() as session:
        repaired_movie = await session.scalar(select(Movie))

    assert repaired.action is IndexAction.QUALITY_UPSERTED
    assert repaired.should_notify_owner
    assert repaired_movie is not None
    assert repaired_movie.status == "indexed"
