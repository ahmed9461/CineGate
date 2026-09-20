from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete

from cinegate.admin.diagnostics import AdminDiagnosticsService
from cinegate.db.models import (
    AdminAuditLog,
    AppSetting,
    Delivery,
    MessageTemplate,
    Movie,
    MovieQuality,
    OwnerEditSession,
    RewardSession,
    UserSearchSession,
)
from cinegate.db.session import Database

DATABASE_URL = os.getenv("CINEGATE_DATABASE_URL")
ARCHIVE_CHANNEL_ID = -1001234567890


async def clean_database(database: Database) -> None:
    async with database.session() as session, session.begin():
        await session.execute(delete(AdminAuditLog))
        await session.execute(delete(OwnerEditSession))
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

    database = Database(DATABASE_URL, pool_size=3, max_overflow=0)
    await clean_database(database)
    try:
        yield database
    finally:
        await clean_database(database)
        await database.dispose()


@pytest.mark.asyncio
async def test_diagnostics_counts_and_problem_lists(database: Database) -> None:
    now = datetime.now(UTC)

    async with database.session() as session, session.begin():
        indexed = Movie(
            archive_channel_id=ARCHIVE_CHANNEL_ID,
            poster_message_id=100,
            display_title="Indexed Movie",
            normalized_title="indexed movie",
            year=2025,
            parser_style="modern",
            status="indexed",
            raw_poster_caption="الفيلم: Indexed Movie",
            parser_confidence=95,
        )
        orphan = Movie(
            archive_channel_id=ARCHIVE_CHANNEL_ID,
            poster_message_id=200,
            display_title="Orphan Movie",
            normalized_title="orphan movie",
            year=2024,
            parser_style="modern",
            status="orphan",
            raw_poster_caption="الفيلم: Orphan Movie",
            parser_confidence=90,
        )
        ambiguous = Movie(
            archive_channel_id=ARCHIVE_CHANNEL_ID,
            poster_message_id=300,
            display_title="Ambiguous Movie",
            normalized_title="ambiguous movie",
            year=2023,
            parser_style="legacy",
            status="ambiguous",
            raw_poster_caption="فيلم: Ambiguous Movie",
            parser_confidence=70,
        )
        pending = Movie(
            archive_channel_id=ARCHIVE_CHANNEL_ID,
            poster_message_id=400,
            display_title="Pending Movie",
            normalized_title="pending movie",
            year=2022,
            parser_style="modern",
            status="pending",
            raw_poster_caption="الفيلم: Pending Movie",
            parser_confidence=90,
        )
        session.add_all([indexed, orphan, ambiguous, pending])
        await session.flush()

        quality = MovieQuality(
            movie_id=indexed.id,
            archive_channel_id=ARCHIVE_CHANNEL_ID,
            archive_message_id=101,
            quality="720p",
            raw_caption="Indexed Movie 2025 #720p",
            extracted_title="Indexed Movie",
            normalized_title="indexed movie",
            extracted_year=2025,
            parser_confidence=95,
        )
        session.add(quality)
        await session.flush()

        rewarded = RewardSession(
            telegram_user_id=1001,
            movie_id=indexed.id,
            movie_quality_id=quality.id,
            quality="720p",
            status="rewarded",
            expires_at=now - timedelta(minutes=1),
            rewarded_at=now,
        )
        sent_reward = RewardSession(
            telegram_user_id=1002,
            movie_id=indexed.id,
            movie_quality_id=quality.id,
            quality="720p",
            status="delivered",
            expires_at=now + timedelta(minutes=5),
            rewarded_at=now,
            delivered_at=now,
        )
        failed_reward = RewardSession(
            telegram_user_id=1003,
            movie_id=indexed.id,
            movie_quality_id=quality.id,
            quality="720p",
            status="delivered",
            expires_at=now + timedelta(minutes=5),
            rewarded_at=now,
            delivered_at=now,
        )
        session.add_all([rewarded, sent_reward, failed_reward])
        await session.flush()

        session.add_all(
            [
                Delivery(
                    reward_session_id=sent_reward.id,
                    telegram_user_id=1002,
                    movie_quality_id=quality.id,
                    status="sent",
                    telegram_message_id=8001,
                    sent_at=now,
                    delete_at=now + timedelta(minutes=2),
                    next_attempt_at=now + timedelta(minutes=2),
                ),
                Delivery(
                    reward_session_id=failed_reward.id,
                    telegram_user_id=1003,
                    movie_quality_id=quality.id,
                    status="delete_failed",
                    telegram_message_id=8002,
                    sent_at=now - timedelta(hours=49),
                    delete_at=now - timedelta(hours=48),
                    last_error="Telegram delete window exceeded 48 hours",
                ),
                AdminAuditLog(
                    owner_user_id=999,
                    action="set",
                    target_type="setting",
                    target_key="search_result_limit",
                    old_value=6,
                    new_value=7,
                ),
            ]
        )

    snapshot = await AdminDiagnosticsService(database).snapshot()

    assert snapshot.indexed_movies == 1
    assert snapshot.pending_movies == 1
    assert snapshot.orphan_movies == 1
    assert snapshot.ambiguous_movies == 1
    assert snapshot.qualities == 1
    assert snapshot.active_rewards == 1
    assert snapshot.rewarded_waiting_delivery == 1
    assert snapshot.sent_waiting_delete == 1
    assert snapshot.delete_failed == 1
    assert snapshot.audit_entries == 1
    assert {movie.status for movie in snapshot.problem_movies} == {
        "orphan",
        "ambiguous",
    }
    assert len(snapshot.failed_deletions) == 1
    assert snapshot.failed_deletions[0].delivery_id > 0
