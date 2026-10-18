from __future__ import annotations

import pytest_asyncio
from sqlalchemy import delete, select
from test_delivery_integration import ARCHIVE_CHANNEL_ID, USER_ID, setup  # noqa: F401

from cinegate.db.archive_models import ArchiveMessageSnapshot
from cinegate.db.models import MovieQuality, RewardSession
from cinegate.domain.archive import ArchiveMessage, MediaKind
from cinegate.repositories.settings import SettingsRepository
from cinegate.services.archive_indexer import ArchiveIndexService
from cinegate.services.reward_sessions import RewardSessionService


@pytest_asyncio.fixture
async def isolated_setup(setup):  # noqa: F811
    database = setup[0]
    async with database.session() as session, session.begin():
        await session.execute(delete(ArchiveMessageSnapshot))
        await SettingsRepository(session).set("archive_channel_id", ARCHIVE_CHANNEL_ID)
    try:
        yield setup
    finally:
        async with database.session() as session, session.begin():
            await session.execute(delete(ArchiveMessageSnapshot))


async def test_real_archive_edit_preserves_reward_and_allows_independent_ad(isolated_setup) -> None:
    database, bot, delivery, earned, quality_id = isolated_setup
    indexer = ArchiveIndexService(database)
    await indexer.reconcile_edit(
        channel_id=ARCHIVE_CHANNEL_ID,
        message=ArchiveMessage(
            message_id=100,
            media_kind=MediaKind.PHOTO,
            caption="الفيلم: Top Gun\nالسنة: 1986\nالقصة: قصة",
        ),
    )
    await indexer.reconcile_edit(
        channel_id=ARCHIVE_CHANNEL_ID,
        message=ArchiveMessage(
            message_id=777,
            media_kind=MediaKind.VIDEO,
            caption="Top Gun 1986 #720p",
        ),
    )
    await indexer.ingest(
        channel_id=ARCHIVE_CHANNEL_ID,
        message=ArchiveMessage(
            message_id=778,
            media_kind=MediaKind.VIDEO,
            caption="Top Gun 1986 #480p",
        ),
    )
    await indexer.reconcile_edit(
        channel_id=ARCHIVE_CHANNEL_ID,
        message=ArchiveMessage(
            message_id=777,
            media_kind=MediaKind.VIDEO,
            caption="Top Gun 1986 #1080p",
        ),
    )
    assert (await delivery.deliver(earned.id)).status == "unavailable"
    assert bot.copies == []
    rewards = RewardSessionService(database)
    independent, created = await rewards.get_or_create(
        telegram_user_id=USER_ID,
        movie_id=earned.movie_id,
        quality="480p",
    )
    assert created and independent.id != earned.id

    await indexer.reconcile_edit(
        channel_id=ARCHIVE_CHANNEL_ID,
        message=ArchiveMessage(
            message_id=777,
            media_kind=MediaKind.VIDEO,
            caption="Top Gun 1986 #720p",
        ),
    )
    restored, created = await rewards.get_or_create(
        telegram_user_id=USER_ID,
        movie_id=earned.movie_id,
        quality="720p",
    )
    assert not created and restored.id == earned.id
    assert (await delivery.deliver(earned.id)).status == "delivered"
    assert len(bot.copies) == 1
    assert bot.copies[0]["message_id"] == 777
    async with database.session() as session:
        original = await session.get(RewardSession, earned.id)
        active = await session.get(RewardSession, independent.id)
        quality = await session.scalar(select(MovieQuality).where(MovieQuality.id == quality_id))
        assert quality.quality == "720p"
        assert original.movie_quality_id == quality_id
        assert original.client_completed_at == earned.client_completed_at
        assert original.provider_confirmed_at == earned.provider_confirmed_at
        assert original.unavailable_at is not None
        assert active.status == "pending"
        assert active.provider_confirmed_at is None
