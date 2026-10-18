from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
import test_delivery_integration as delivery_tests
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import CopyMessage
from sqlalchemy import select

from cinegate.db.models import Delivery, Movie, MovieQuality, RewardSession
from cinegate.services.reward_sessions import RewardSessionService

ARCHIVE_CHANNEL_ID = delivery_tests.ARCHIVE_CHANNEL_ID
USER_ID = delivery_tests.USER_ID
setup = delivery_tests.setup


async def other_quality(database, movie_id: int) -> None:
    async with database.session() as session, session.begin():
        session.add(MovieQuality(
            movie_id=movie_id, archive_channel_id=ARCHIVE_CHANNEL_ID,
            archive_message_id=778, quality="1080p", raw_caption="Top Gun 1986 #1080p",
            extracted_title="Top Gun", normalized_title="top gun", extracted_year=1986,
            parser_confidence=95,
        ))


@pytest.mark.asyncio
async def test_unavailable_reward_releases_slot_and_preserves_proof(setup) -> None:
    database, bot, delivery, reward, quality_id = setup
    await other_quality(database, reward.movie_id)
    async with database.session() as session, session.begin():
        quality = await session.get(MovieQuality, quality_id)
        quality.parser_confidence = 0
        row = await session.get(RewardSession, reward.id)
        row.expires_at = datetime.now(UTC) - timedelta(days=7)

    result = await delivery.deliver(reward.id)
    assert result.status == "unavailable"
    rewards = RewardSessionService(database)
    new, created = await rewards.get_or_create(
        telegram_user_id=USER_ID, movie_id=reward.movie_id, quality="1080p",
    )
    assert created and new.id != reward.id
    retained = await rewards.get(reward.id)
    assert retained.status == "unavailable"
    assert retained.is_rewarded
    assert retained.client_completed_at == reward.client_completed_at
    assert retained.provider_confirmed_at == reward.provider_confirmed_at
    assert retained.movie_quality_id == quality_id
    assert bot.copies == []


@pytest.mark.asyncio
async def test_creation_reconciles_changed_reward_before_active_conflict(setup) -> None:
    database, _bot, _delivery, reward, quality_id = setup
    async with database.session() as session, session.begin():
        quality = await session.get(MovieQuality, quality_id)
        quality.quality = "1080p"

    rewards = RewardSessionService(database)
    new, created = await rewards.get_or_create(
        telegram_user_id=USER_ID, movie_id=reward.movie_id, quality="1080p",
    )
    assert created and new.id != reward.id
    assert new.quality == "1080p"
    assert (await rewards.get(reward.id)).status == "unavailable"


@pytest.mark.asyncio
async def test_restored_entitlement_resumes_during_another_active_session(setup) -> None:
    database, bot, delivery, reward, quality_id = setup
    await other_quality(database, reward.movie_id)
    async with database.session() as session, session.begin():
        quality = await session.get(MovieQuality, quality_id)
        quality.parser_confidence = 0
    assert (await delivery.deliver(reward.id)).status == "unavailable"

    rewards = RewardSessionService(database)
    active, _ = await rewards.get_or_create(
        telegram_user_id=USER_ID, movie_id=reward.movie_id, quality="1080p",
    )
    async with database.session() as session, session.begin():
        quality = await session.get(MovieQuality, quality_id)
        quality.parser_confidence = 95
    restored, created = await rewards.get_or_create(
        telegram_user_id=USER_ID, movie_id=reward.movie_id, quality="720p",
    )
    assert restored.id == reward.id and not created
    assert restored.client_completed_at == reward.client_completed_at
    results = await asyncio.gather(delivery.deliver(reward.id), delivery.deliver(reward.id))
    assert all(result.status in {"delivered", "processing"} for result in results)
    assert len(bot.copies) == 1
    assert bot.copies[0]["message_id"] == 777
    assert (await rewards.get(active.id)).status == "pending"
    assert (await rewards.get(reward.id)).status == "delivered"


@pytest.mark.asyncio
async def test_missing_source_is_unavailable_not_transient_and_can_resume(setup) -> None:
    database, bot, delivery, reward, _quality_id = setup
    await other_quality(database, reward.movie_id)
    original_copy = bot.copy_message
    bot.copy_message = AsyncMock(side_effect=TelegramBadRequest(
        method=CopyMessage(chat_id=USER_ID, from_chat_id=ARCHIVE_CHANNEL_ID, message_id=777),
        message="Bad Request: message to copy not found",
    ))
    assert (await delivery.deliver(reward.id)).status == "unavailable"
    rewards = RewardSessionService(database)
    active, _ = await rewards.get_or_create(
        telegram_user_id=USER_ID, movie_id=reward.movie_id, quality="1080p",
    )
    bot.copy_message = original_copy
    assert (await delivery.deliver(reward.id)).status == "delivered"
    assert (await rewards.get(active.id)).status == "pending"
    async with database.session() as session:
        rows = (await session.scalars(select(Delivery).where(
            Delivery.reward_session_id == reward.id,
        ))).all()
        assert len(rows) == 1
        assert rows[0].attempts == 1


@pytest.mark.asyncio
async def test_duplicate_proofs_do_not_reactivate_unavailable_entitlement(setup) -> None:
    database, _bot, delivery, reward, quality_id = setup
    async with database.session() as session, session.begin():
        quality = await session.get(MovieQuality, quality_id)
        quality.quality = "1080p"
    assert (await delivery.deliver(reward.id)).status == "unavailable"
    rewards = RewardSessionService(database)
    assert await rewards.mark_provider_confirmed(telegram_user_id=USER_ID) is None
    repeated = await rewards.mark_client_completed(session_id=reward.id, telegram_user_id=USER_ID)
    assert repeated.status == "unavailable"
    assert repeated.client_completed_at == reward.client_completed_at
    assert repeated.provider_confirmed_at == reward.provider_confirmed_at


@pytest.mark.asyncio
async def test_changed_movie_binding_cannot_replace_original_entitlement(setup) -> None:
    database, bot, delivery, reward, quality_id = setup
    async with database.session() as session, session.begin():
        quality = await session.get(MovieQuality, quality_id)
        replacement = Movie(
            archive_channel_id=ARCHIVE_CHANNEL_ID, poster_message_id=900,
            display_title="Other", normalized_title="other", year=2000,
            parser_style="modern", status="indexed", raw_poster_caption="الفيلم: Other",
            parser_confidence=95,
        )
        session.add(replacement)
        await session.flush()
        quality.movie_id = replacement.id
    assert (await delivery.deliver(reward.id)).status == "unavailable"
    assert bot.copies == []


@pytest.mark.asyncio
async def test_resuming_credit_is_not_provider_target_and_recovers(setup) -> None:
    database, _bot, delivery, reward, quality_id = setup
    await other_quality(database, reward.movie_id)
    async with database.session() as session, session.begin():
        quality = await session.get(MovieQuality, quality_id)
        quality.parser_confidence = 0
    assert (await delivery.deliver(reward.id)).status == "unavailable"
    rewards = RewardSessionService(database)
    active, _ = await rewards.get_or_create(
        telegram_user_id=USER_ID, movie_id=reward.movie_id, quality="1080p",
    )
    async with database.session() as session, session.begin():
        quality = await session.get(MovieQuality, quality_id)
        quality.parser_confidence = 95
    prepared = await delivery._prepare(reward.id)
    assert not hasattr(prepared, "status")
    callback = await rewards.mark_provider_confirmed(telegram_user_id=USER_ID)
    assert callback.id == active.id
    assert callback.status == "provider_confirmed"
    replay = await rewards.mark_client_completed(session_id=reward.id, telegram_user_id=USER_ID)
    assert replay.status == "delivering"
    assert replay.client_completed_at == reward.client_completed_at
    assert replay.provider_confirmed_at == reward.provider_confirmed_at

    from cinegate.admin.diagnostics import AdminDiagnosticsService

    snapshot = await AdminDiagnosticsService(database).snapshot()
    assert snapshot.active_rewards == 1
    async with database.session() as session, session.begin():
        row = await session.scalar(select(Delivery).where(Delivery.reward_session_id == reward.id))
        row.send_started_at = datetime.now(UTC) - timedelta(minutes=10)
    assert await delivery.recover_stale_sends(stale_seconds=60) == 1
    assert (await rewards.get(reward.id)).status == "unavailable"
    assert (await delivery.deliver(reward.id)).status == "delivered"
    assert (await rewards.get(active.id)).status == "provider_confirmed"


@pytest.mark.asyncio
async def test_restored_credit_transient_failure_remains_preserved(setup) -> None:
    database, bot, delivery, reward, quality_id = setup
    await other_quality(database, reward.movie_id)
    async with database.session() as session, session.begin():
        quality = await session.get(MovieQuality, quality_id)
        quality.parser_confidence = 0
    assert (await delivery.deliver(reward.id)).status == "unavailable"
    rewards = RewardSessionService(database)
    active, _ = await rewards.get_or_create(
        telegram_user_id=USER_ID, movie_id=reward.movie_id, quality="1080p",
    )
    async with database.session() as session, session.begin():
        quality = await session.get(MovieQuality, quality_id)
        quality.parser_confidence = 95
    bot.fail_next_copy = True
    assert (await delivery.deliver(reward.id)).status == "retryable"
    assert (await rewards.get(reward.id)).status == "unavailable"
    assert (await rewards.get(active.id)).status == "pending"
    assert (await delivery.deliver(reward.id)).status == "delivered"


@pytest.mark.asyncio
async def test_concurrent_new_requests_after_unavailable_have_one_active_winner(setup) -> None:
    database, _bot, _delivery, reward, quality_id = setup
    async with database.session() as session, session.begin():
        quality = await session.get(MovieQuality, quality_id)
        quality.quality = "1080p"
    rewards = RewardSessionService(database)
    results = await asyncio.gather(*(
        rewards.get_or_create(
            telegram_user_id=USER_ID, movie_id=reward.movie_id, quality="1080p",
        ) for _ in range(3)
    ))
    assert len({row.id for row, _created in results}) == 1
    assert sum(created for _row, created in results) == 1
    assert (await rewards.get(reward.id)).status == "unavailable"


@pytest.mark.asyncio
async def test_same_row_safe_replacement_remains_supported(setup) -> None:
    database, bot, delivery, reward, quality_id = setup
    async with database.session() as session, session.begin():
        quality = await session.get(MovieQuality, quality_id)
        quality.archive_message_id = 999
    assert (await delivery.deliver(reward.id)).status == "delivered"
    assert bot.copies[0]["message_id"] == 999


@pytest.mark.asyncio
async def test_whole_movie_unavailability_does_not_block_unrelated_movie(setup) -> None:
    database, bot, _delivery, reward, _quality_id = setup
    async with database.session() as session, session.begin():
        original = await session.get(Movie, reward.movie_id)
        original.status = "ambiguous"
        other = Movie(
            archive_channel_id=ARCHIVE_CHANNEL_ID, poster_message_id=900,
            display_title="Other", normalized_title="other", year=2000,
            parser_style="modern", status="indexed", raw_poster_caption="الفيلم: Other",
            parser_confidence=95,
        )
        session.add(other)
        await session.flush()
        session.add(MovieQuality(
            movie_id=other.id, archive_channel_id=ARCHIVE_CHANNEL_ID,
            archive_message_id=901, quality="720p", raw_caption="Other 2000 #720p",
            extracted_title="Other", normalized_title="other", extracted_year=2000,
            parser_confidence=95,
        ))
        other_id = other.id
    rewards = RewardSessionService(database)
    unrelated, created = await rewards.get_or_create(
        telegram_user_id=USER_ID, movie_id=other_id, quality="720p",
    )
    assert created and unrelated.movie_id == other_id
    assert unrelated.status == "pending"
    retained = await rewards.get(reward.id)
    assert retained.status == "unavailable"
    assert retained.movie_id == reward.movie_id
    assert retained.movie_quality_id == reward.movie_quality_id
    assert retained.client_completed_at == reward.client_completed_at
    assert retained.provider_confirmed_at == reward.provider_confirmed_at
    assert bot.copies == []
