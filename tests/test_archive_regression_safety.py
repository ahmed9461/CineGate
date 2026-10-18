from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text

from cinegate.db.base import Base
from cinegate.db.models import Movie, MovieQuality
from cinegate.db.session import Database
from cinegate.domain.archive import ArchiveMessage, MediaKind
from cinegate.repositories.settings import SettingsRepository
from cinegate.services.archive_indexer import ArchiveIndexService
from cinegate.services.archive_parser import ArchiveParser
from cinegate.services.movie_search import MovieSearchService

ARCHIVE = -1001234567890


def poster(year=2014):
    return ArchiveMessage(100, MediaKind.PHOTO, f"الفيلم: Interstellar\nالسنة: {year}\nالقصة: قصة")


def quality(message_id=101, resolution="720p"):
    return ArchiveMessage(message_id, MediaKind.VIDEO, f"Interstellar 2014 #{resolution}")


@pytest_asyncio.fixture
async def database():
    url = os.getenv("CINEGATE_DATABASE_URL")
    if not url:
        pytest.skip("CINEGATE_DATABASE_URL is not configured")
    database = Database(url)

    async def clean():
        async with database.session() as session, session.begin():
            for table in reversed(Base.metadata.sorted_tables):
                await session.execute(delete(table))
            await SettingsRepository(session).set("archive_channel_id", ARCHIVE)

    await clean()
    try:
        yield database
    finally:
        await clean()
        await database.dispose()


async def ingest(database, messages):
    for message in messages:
        await ArchiveIndexService(database).ingest(channel_id=ARCHIVE, message=message)


async def rows(database):
    async with database.session() as session:
        return await session.scalar(select(Movie).order_by(Movie.id)), (
            await session.scalars(select(MovieQuality).order_by(MovieQuality.archive_message_id))
        ).all()


@pytest.mark.parametrize("kind", [MediaKind.OTHER, MediaKind.PHOTO, MediaKind.VIDEO])
async def test_persisted_noise_boundary_matches_parser_across_restart(database, kind):
    messages = [
        poster(),
        ArchiveMessage(101, kind, "unrelated"),
        ArchiveMessage(102, kind, "unrelated"),
        quality(103),
    ]
    assert not ArchiveParser().parse(messages)[0].qualities
    await ingest(database, messages)
    movie, qualities = await rows(database)
    assert movie.status == "orphan"
    assert qualities == []


async def test_noise_reset_and_distance_match_full_stream_parser(database):
    messages = [
        poster(),
        ArchiveMessage(101, MediaKind.OTHER),
        quality(102),
        ArchiveMessage(103, MediaKind.OTHER),
        quality(104, "1080p"),
    ]
    await ingest(database, messages)
    movie, qualities = await rows(database)
    expected = ArchiveParser().parse(messages)[0]
    assert movie.status == "indexed"
    assert {q.archive_message_id: q.parser_confidence for q in qualities} == {
        q.message_id: q.confidence for q in expected.qualities
    }


async def test_poster_edit_revalidates_and_repair_restores_exact_quality_rows(database):
    await ingest(database, [poster(), quality(), quality(102, "1080p")])
    _, original = await rows(database)
    indexer = ArchiveIndexService(database)
    await indexer.reconcile_edit(channel_id=ARCHIVE, message=poster(2015))
    movie, qualities = await rows(database)
    assert movie.status == "ambiguous"
    assert all(q.parser_confidence == 0 for q in qualities)
    assert await MovieSearchService(database).search("Interstellar") == ()
    await indexer.reconcile_edit(channel_id=ARCHIVE, message=poster())
    movie, qualities = await rows(database)
    assert movie.status == "indexed"
    assert [q.id for q in qualities] == [q.id for q in original]
    assert all(q.parser_confidence > 0 for q in qualities)


@pytest.mark.parametrize("edited", [poster(2015), ArchiveMessage(100, MediaKind.PHOTO, "removed")])
async def test_original_poster_replay_cannot_undo_edit(database, edited):
    await ingest(database, [poster(), quality()])
    await ArchiveIndexService(database).reconcile_edit(channel_id=ARCHIVE, message=edited)
    await ingest(database, [poster(), quality()])
    movie, _ = await rows(database)
    assert movie.raw_poster_caption == edited.caption
    assert movie.status == "ambiguous"
    assert await MovieSearchService(database).search("Interstellar") == ()


async def test_older_edit_and_stale_history_cannot_replace_newer_invalidation(database):
    await ingest(database, [poster(), quality()])
    now = datetime(2026, 10, 15, tzinfo=UTC)
    indexer = ArchiveIndexService(database)
    newest = replace(poster(), caption="removed", edited_at=now)
    await indexer.reconcile_edit(channel_id=ARCHIVE, message=newest)
    for stale in [
        replace(poster(), edited_at=now - timedelta(seconds=1)),
        replace(poster(), edited_at=now),
        poster(),
    ]:
        await indexer.reconcile_edit(channel_id=ARCHIVE, message=stale)
    movie, _ = await rows(database)
    assert movie.status == "ambiguous"
    assert movie.raw_poster_caption == "removed"
    await indexer.reconcile_edit(
        channel_id=ARCHIVE, message=replace(poster(), edited_at=now + timedelta(seconds=1))
    )
    movie, _ = await rows(database)
    assert movie.status == "indexed"


async def test_ignored_edit_creates_boundary_without_reassigning_quality(
    database,
):
    await ingest(database, [poster(), ArchiveMessage(101, MediaKind.OTHER), quality(102)])
    movie, qualities = await rows(database)
    original_movie_id = movie.id
    original_quality_id = qualities[0].id
    await ArchiveIndexService(database).reconcile_edit(
        channel_id=ARCHIVE, message=replace(poster(), message_id=101)
    )
    movie, qualities = await rows(database)
    assert movie.status == "ambiguous"
    assert qualities[0].id == original_quality_id
    assert qualities[0].movie_id == original_movie_id
    assert qualities[0].parser_confidence == 0


async def test_delayed_boundary_evidence_invalidates_already_attached_file(database):
    await ingest(database, [poster(), quality(103)])
    await ingest(
        database, [ArchiveMessage(101, MediaKind.OTHER), ArchiveMessage(102, MediaKind.OTHER)]
    )
    movie, qualities = await rows(database)
    assert movie.status == "ambiguous"
    assert qualities[0].parser_confidence == 0


async def test_original_quality_replay_after_resolution_edit_is_safe(database):
    await ingest(database, [poster(), quality()])
    await ArchiveIndexService(database).reconcile_edit(
        channel_id=ARCHIVE, message=quality(resolution="1080p")
    )
    await ingest(database, [quality()])
    movie, qualities = await rows(database)
    assert movie.status == "indexed"
    assert len(qualities) == 1
    assert qualities[0].quality == "1080p"


async def test_snapshot_and_index_rollback_together_and_retry_succeeds(database, monkeypatch):
    await ingest(database, [poster()])
    indexer = ArchiveIndexService(database)
    original = indexer._upsert_quality

    async def fail(**kwargs):
        raise RuntimeError("synthetic database transaction failure")

    monkeypatch.setattr(indexer, "_upsert_quality", fail)
    with pytest.raises(RuntimeError, match="synthetic"):
        await indexer.ingest(channel_id=ARCHIVE, message=quality())
    async with database.session() as session:
        count = await session.scalar(
            text("SELECT count(*) FROM archive_message_snapshots WHERE message_id = 101")
        )
    assert count == 0
    monkeypatch.setattr(indexer, "_upsert_quality", original)
    await indexer.ingest(channel_id=ARCHIVE, message=quality())
    movie, qualities = await rows(database)
    assert movie.status == "indexed"
    assert len(qualities) == 1


async def test_history_token_repairs_same_second_edit_and_rejects_intervening_live_event(database):
    await ingest(database, [poster(), quality()])
    indexer = ArchiveIndexService(database)
    now = datetime(2026, 10, 15, tzinfo=UTC)
    invalid = replace(poster(), caption="removed", edited_at=now)
    await indexer.reconcile_edit(channel_id=ARCHIVE, message=invalid)
    versions = await indexer.snapshot_versions(ARCHIVE, [100])
    await indexer.reconcile_edit(
        channel_id=ARCHIVE,
        message=replace(poster(), edited_at=now),
        expected_snapshot_version=versions[100],
    )
    movie, _ = await rows(database)
    assert movie.status == "indexed"

    versions = await indexer.snapshot_versions(ARCHIVE, [100])
    await indexer.reconcile_edit(
        channel_id=ARCHIVE, message=replace(invalid, edited_at=now + timedelta(seconds=1))
    )
    await indexer.reconcile_edit(
        channel_id=ARCHIVE,
        message=replace(poster(), edited_at=now + timedelta(seconds=1)),
        expected_snapshot_version=versions[100],
    )
    movie, _ = await rows(database)
    assert movie.status == "ambiguous"
    assert movie.raw_poster_caption == "removed"


async def test_current_history_retries_resolution_conflict_after_slot_is_freed(database):
    await ingest(database, [poster(), quality(), quality(102, "1080p")])
    indexer = ArchiveIndexService(database)
    now = datetime(2026, 10, 15, tzinfo=UTC)
    corrected = replace(quality(resolution="1080p"), edited_at=now)
    await indexer.reconcile_edit(channel_id=ARCHIVE, message=corrected)
    movie, _ = await rows(database)
    assert movie.status == "ambiguous"
    await indexer.reconcile_edit(
        channel_id=ARCHIVE, message=replace(quality(102, "480p"), edited_at=now)
    )
    versions = await indexer.snapshot_versions(ARCHIVE, [101])
    await indexer.reconcile_edit(
        channel_id=ARCHIVE, message=corrected, expected_snapshot_version=versions[101]
    )
    movie, qualities = await rows(database)
    assert movie.status == "indexed"
    assert [row.quality for row in qualities] == ["1080p", "480p"]


async def test_same_second_live_conflict_is_unsafe_and_fences_inflight_history(database):
    await ingest(database, [poster(), quality()])
    indexer = ArchiveIndexService(database)
    now = datetime(2026, 10, 15, tzinfo=UTC)
    safe = replace(poster(), edited_at=now)
    await indexer.reconcile_edit(channel_id=ARCHIVE, message=safe)
    before = await indexer.snapshot_versions(ARCHIVE, [100])
    await indexer.reconcile_edit(channel_id=ARCHIVE, message=replace(safe, caption="removed"))
    movie, _ = await rows(database)
    assert movie.status == "ambiguous"
    assert movie.raw_poster_caption == safe.caption
    await indexer.reconcile_edit(
        channel_id=ARCHIVE, message=safe, expected_snapshot_version=before[100]
    )
    movie, _ = await rows(database)
    assert movie.status == "ambiguous"
    fresh = await indexer.snapshot_versions(ARCHIVE, [100])
    assert fresh[100] > before[100]
    await indexer.reconcile_edit(
        channel_id=ARCHIVE, message=safe, expected_snapshot_version=fresh[100]
    )
    movie, _ = await rows(database)
    assert movie.status == "indexed"


async def test_unknown_same_second_conflict_blocks_group_until_current_history_repairs(database):
    now = datetime(2026, 10, 15, tzinfo=UTC)
    noise = ArchiveMessage(101, MediaKind.OTHER, "announcement", edited_at=now)
    await ingest(database, [poster(), noise, quality(102)])
    indexer = ArchiveIndexService(database)
    before = await indexer.snapshot_versions(ARCHIVE, [101])
    await indexer.reconcile_edit(
        channel_id=ARCHIVE, message=replace(poster(), message_id=101, edited_at=now)
    )
    movie, qualities = await rows(database)
    assert movie.status == "ambiguous"
    assert qualities[0].parser_confidence == 0
    await ingest(database, [poster(), quality(103, "1080p")])
    movie, _ = await rows(database)
    assert movie.status == "ambiguous"
    await indexer.reconcile_edit(
        channel_id=ARCHIVE, message=noise, expected_snapshot_version=before[101]
    )
    movie, _ = await rows(database)
    assert movie.status == "ambiguous"
    fresh = await indexer.snapshot_versions(ARCHIVE, [101])
    await indexer.reconcile_edit(
        channel_id=ARCHIVE, message=noise, expected_snapshot_version=fresh[101]
    )
    movie, qualities = await rows(database)
    assert movie.status == "indexed"
    assert qualities[0].parser_confidence > 0
