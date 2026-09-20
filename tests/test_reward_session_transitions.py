from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, update

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
from cinegate.domain.rewards import RewardSessionExpired, RewardUserMismatch
from cinegate.services.reward_sessions import RewardSessionService

DATABASE_URL = os.getenv("CINEGATE_DATABASE_URL")
ARCHIVE_CHANNEL_ID = -1001234567890
USER_ID = 111111


@pytest_asyncio.fixture
async def reward_setup() -> tuple[Database, int]:
    if not DATABASE_URL:
        pytest.skip("CINEGATE_DATABASE_URL is not configured")

    database = Database(DATABASE_URL, pool_size=3, max_overflow=0)
    async with database.session() as session, session.begin():
        await session.execute(delete(Delivery))
        await session.execute(delete(RewardSession))
        await session.execute(delete(UserSearchSession))
        await session.execute(delete(MovieQuality))
        await session.execute(delete(Movie))
        await session.execute(delete(AppSetting))
        await session.execute(delete(MessageTemplate))

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
        session.add(
            MovieQuality(
                movie_id=movie.id,
                archive_channel_id=ARCHIVE_CHANNEL_ID,
                archive_message_id=101,
                quality="720p",
                raw_caption="Interstellar 2014 #720p",
                extracted_title="Interstellar",
                normalized_title="interstellar",
                extracted_year=2014,
                parser_confidence=95,
            )
        )
        await session.flush()
        movie_id = movie.id

    try:
        yield database, movie_id
    finally:
        async with database.session() as session, session.begin():
            await session.execute(delete(Delivery))
            await session.execute(delete(RewardSession))
            await session.execute(delete(UserSearchSession))
            await session.execute(delete(MovieQuality))
            await session.execute(delete(Movie))
            await session.execute(delete(AppSetting))
            await session.execute(delete(MessageTemplate))
        await database.dispose()


@pytest.mark.asyncio
async def test_client_then_provider_is_rewarded(reward_setup) -> None:
    database, movie_id = reward_setup
    service = RewardSessionService(database)
    reward, _ = await service.get_or_create(
        telegram_user_id=USER_ID,
        movie_id=movie_id,
        quality="720p",
    )

    client = await service.mark_client_completed(
        session_id=reward.id,
        telegram_user_id=USER_ID,
    )
    assert client.status == "client_completed"

    provider = await service.mark_provider_confirmed(telegram_user_id=USER_ID)
    assert provider is not None
    assert provider.status == "rewarded"


@pytest.mark.asyncio
async def test_provider_then_client_is_rewarded(reward_setup) -> None:
    database, movie_id = reward_setup
    service = RewardSessionService(database)
    reward, _ = await service.get_or_create(
        telegram_user_id=USER_ID,
        movie_id=movie_id,
        quality="720p",
    )

    provider = await service.mark_provider_confirmed(telegram_user_id=USER_ID)
    assert provider is not None
    assert provider.status == "provider_confirmed"

    client = await service.mark_client_completed(
        session_id=reward.id,
        telegram_user_id=USER_ID,
    )
    assert client.status == "rewarded"


@pytest.mark.asyncio
async def test_duplicate_confirmations_are_idempotent(reward_setup) -> None:
    database, movie_id = reward_setup
    service = RewardSessionService(database)
    reward, _ = await service.get_or_create(
        telegram_user_id=USER_ID,
        movie_id=movie_id,
        quality="720p",
    )

    first = await service.mark_client_completed(
        session_id=reward.id,
        telegram_user_id=USER_ID,
    )
    second = await service.mark_client_completed(
        session_id=reward.id,
        telegram_user_id=USER_ID,
    )
    assert second.client_completed_at == first.client_completed_at

    provider1 = await service.mark_provider_confirmed(telegram_user_id=USER_ID)
    provider2 = await service.mark_provider_confirmed(telegram_user_id=USER_ID)
    assert provider1 is not None
    assert provider2 is not None
    assert provider2.provider_confirmed_at == provider1.provider_confirmed_at


@pytest.mark.asyncio
async def test_other_user_cannot_claim(reward_setup) -> None:
    database, movie_id = reward_setup
    service = RewardSessionService(database)
    reward, _ = await service.get_or_create(
        telegram_user_id=USER_ID,
        movie_id=movie_id,
        quality="720p",
    )

    with pytest.raises(RewardUserMismatch):
        await service.mark_client_completed(
            session_id=reward.id,
            telegram_user_id=222222,
        )


@pytest.mark.asyncio
async def test_expired_session_allows_new_reward(reward_setup) -> None:
    database, movie_id = reward_setup
    service = RewardSessionService(database)
    old, _ = await service.get_or_create(
        telegram_user_id=USER_ID,
        movie_id=movie_id,
        quality="720p",
    )

    async with database.session() as session, session.begin():
        await session.execute(
            update(RewardSession)
            .where(RewardSession.id == old.id)
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )

    with pytest.raises(RewardSessionExpired):
        await service.get(old.id)

    new, created = await service.get_or_create(
        telegram_user_id=USER_ID,
        movie_id=movie_id,
        quality="720p",
    )
    assert created
    assert new.id != old.id

    async with database.session() as session:
        status = await session.scalar(
            select(RewardSession.status).where(RewardSession.id == old.id)
        )
    assert status == "expired"
