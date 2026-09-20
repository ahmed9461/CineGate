from __future__ import annotations

import os

import pytest
import pytest_asyncio
from sqlalchemy import delete

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
from cinegate.domain.rewards import ActiveRewardConflict
from cinegate.services.reward_sessions import RewardSessionService

DATABASE_URL = os.getenv("CINEGATE_DATABASE_URL")
ARCHIVE_CHANNEL_ID = -1001234567890
USER_ID = 111111


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

    database = Database(DATABASE_URL, pool_size=3, max_overflow=0)
    await clean_database(database)
    try:
        yield database
    finally:
        await clean_database(database)
        await database.dispose()


async def seed_movie(database: Database) -> tuple[int, dict[str, int]]:
    async with database.session() as session, session.begin():
        movie = Movie(
            archive_channel_id=ARCHIVE_CHANNEL_ID,
            poster_message_id=100,
            display_title="Interstellar",
            normalized_title="interstellar",
            year=2014,
            parser_style="modern",
            status="indexed",
            raw_poster_caption="الفيلم: Interstellar",
            parser_confidence=95,
        )
        session.add(movie)
        await session.flush()

        quality_ids: dict[str, int] = {}
        for message_id, quality in ((101, "720p"), (102, "1080p")):
            row = MovieQuality(
                movie_id=movie.id,
                archive_channel_id=ARCHIVE_CHANNEL_ID,
                archive_message_id=message_id,
                quality=quality,
                raw_caption=f"Interstellar 2014 #{quality}",
                extracted_title="Interstellar",
                normalized_title="interstellar",
                extracted_year=2014,
                parser_confidence=95,
            )
            session.add(row)
            await session.flush()
            quality_ids[quality] = row.id

        return movie.id, quality_ids


@pytest.mark.asyncio
async def test_exact_binding_and_same_target_reuse(database: Database) -> None:
    movie_id, quality_ids = await seed_movie(database)
    service = RewardSessionService(database)

    first, created = await service.get_or_create(
        telegram_user_id=USER_ID,
        movie_id=movie_id,
        quality="720p",
    )
    second, second_created = await service.get_or_create(
        telegram_user_id=USER_ID,
        movie_id=movie_id,
        quality="720p",
    )

    assert created
    assert not second_created
    assert first.id == second.id
    assert first.movie_quality_id == quality_ids["720p"]


@pytest.mark.asyncio
async def test_different_quality_cannot_replace_active_reward(database: Database) -> None:
    movie_id, _ = await seed_movie(database)
    service = RewardSessionService(database)

    active, _ = await service.get_or_create(
        telegram_user_id=USER_ID,
        movie_id=movie_id,
        quality="720p",
    )

    with pytest.raises(ActiveRewardConflict) as exc_info:
        await service.get_or_create(
            telegram_user_id=USER_ID,
            movie_id=movie_id,
            quality="1080p",
        )

    assert exc_info.value.session.id == active.id
    assert exc_info.value.session.quality == "720p"
