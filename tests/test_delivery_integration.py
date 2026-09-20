from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from aiogram.enums import MessageEntityType
from aiogram.exceptions import TelegramAPIError
from aiogram.types import MessageEntity
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

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
from cinegate.presentation.templates import serialize_entities
from cinegate.services.delivery import DeliveryService
from cinegate.services.reward_sessions import RewardSessionService

DATABASE_URL = os.getenv("CINEGATE_DATABASE_URL")
ARCHIVE_CHANNEL_ID = -1001234567890
USER_ID = 123456789


class FakeTelegramFailure(TelegramAPIError):
    def __init__(self, message: str = "temporary Telegram failure") -> None:
        Exception.__init__(self, message)
        self.message = message
        self.method = None


class FakeBot:
    def __init__(self) -> None:
        self.copies: list[dict] = []
        self.fail_next_copy = False
        self.next_message_id = 8000

    async def copy_message(self, **kwargs):
        self.copies.append(kwargs)
        if self.fail_next_copy:
            self.fail_next_copy = False
            raise FakeTelegramFailure()
        result = SimpleNamespace(message_id=self.next_message_id)
        self.next_message_id += 1
        return result


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
async def setup():
    if not DATABASE_URL:
        pytest.skip("CINEGATE_DATABASE_URL is not configured")

    database = Database(DATABASE_URL, pool_size=3, max_overflow=0)
    await clean_database(database)

    async with database.session() as session, session.begin():
        movie = Movie(
            archive_channel_id=ARCHIVE_CHANNEL_ID,
            poster_message_id=100,
            display_title="Top Gun",
            normalized_title="top gun",
            year=1986,
            parser_style="modern",
            status="indexed",
            raw_poster_caption="الفيلم: Top Gun",
            parser_confidence=95,
        )
        session.add(movie)
        await session.flush()

        quality = MovieQuality(
            movie_id=movie.id,
            archive_channel_id=ARCHIVE_CHANNEL_ID,
            archive_message_id=777,
            quality="720p",
            raw_caption="Top Gun 1986 #720p",
            extracted_title="Top Gun",
            normalized_title="top gun",
            extracted_year=1986,
            parser_confidence=95,
        )
        session.add(quality)
        await session.flush()
        movie_id = movie.id
        quality_id = quality.id

    rewards = RewardSessionService(database)
    reward, _ = await rewards.get_or_create(
        telegram_user_id=USER_ID,
        movie_id=movie_id,
        quality="720p",
    )
    await rewards.mark_client_completed(
        session_id=reward.id,
        telegram_user_id=USER_ID,
    )
    rewarded = await rewards.mark_provider_confirmed(
        telegram_user_id=USER_ID,
    )
    assert rewarded is not None
    assert rewarded.status == "rewarded"

    bot = FakeBot()
    delivery = DeliveryService(database, bot)

    try:
        yield database, bot, delivery, rewarded, quality_id
    finally:
        await clean_database(database)
        await database.dispose()


async def set_setting(database: Database, key: str, value) -> None:
    async with database.session() as session, session.begin():
        statement = insert(AppSetting).values(key=key, value=value)
        statement = statement.on_conflict_do_update(
            index_elements=[AppSetting.key],
            set_={"value": statement.excluded.value},
        )
        await session.execute(statement)


@pytest.mark.asyncio
async def test_rewarded_exact_quality_is_copied_and_expiry_persisted(setup) -> None:
    database, bot, delivery, reward, quality_id = setup
    await set_setting(database, "movie_delete_seconds", 120)

    result = await delivery.deliver(reward.id)

    assert result.status == "delivered"
    assert result.telegram_message_id == 8000
    assert result.delete_at is not None
    assert len(bot.copies) == 1
    call = bot.copies[0]
    assert call["chat_id"] == USER_ID
    assert call["from_chat_id"] == ARCHIVE_CHANNEL_ID
    assert call["message_id"] == 777
    assert call["protect_content"] is False
    assert "Top Gun 1986 720p" in call["caption"]
    assert "120 ثانية" in call["caption"]

    async with database.session() as session:
        row = await session.scalar(
            select(Delivery).where(Delivery.reward_session_id == reward.id)
        )
        reward_row = await session.get(RewardSession, reward.id)

    assert row is not None
    assert row.movie_quality_id == quality_id
    assert row.telegram_message_id == 8000
    assert row.status == "sent"
    assert row.delete_at == result.delete_at
    assert reward_row is not None
    assert reward_row.status == "delivered"


@pytest.mark.asyncio
async def test_duplicate_delivery_call_does_not_copy_again(setup) -> None:
    _database, bot, delivery, reward, _quality_id = setup

    first = await delivery.deliver(reward.id)
    second = await delivery.deliver(reward.id)

    assert first.status == "delivered"
    assert second.status == "delivered"
    assert first.telegram_message_id == second.telegram_message_id
    assert len(bot.copies) == 1


@pytest.mark.asyncio
async def test_custom_caption_and_time_setting_are_applied(setup) -> None:
    database, bot, delivery, reward, _quality_id = setup
    await set_setting(database, "movie_delete_seconds", 45)

    async with database.session() as session, session.begin():
        session.add(
            MessageTemplate(
                key="delivery_caption",
                body="%movie% | %year% | %quality% | يحذف بعد %time%",
            )
        )

    result = await delivery.deliver(reward.id)

    assert result.status == "delivered"
    assert bot.copies[0]["caption"] == "Top Gun | 1986 | 720p | يحذف بعد 45 ثانية"


@pytest.mark.asyncio
async def test_invalid_owner_caption_falls_back_to_safe_default(setup) -> None:
    database, bot, delivery, reward, _quality_id = setup

    async with database.session() as session, session.begin():
        session.add(
            MessageTemplate(
                key="delivery_caption",
                body="%movie% %unsupported_variable%",
            )
        )

    result = await delivery.deliver(reward.id)

    assert result.status == "delivered"
    assert "Top Gun 1986 720p" in bot.copies[0]["caption"]


@pytest.mark.asyncio
async def test_telegram_copy_failure_keeps_reward_reusable(setup) -> None:
    database, bot, delivery, reward, _quality_id = setup
    bot.fail_next_copy = True

    failed = await delivery.deliver(reward.id)

    assert failed.status == "retryable"

    async with database.session() as session:
        reward_row = await session.get(RewardSession, reward.id)
        delivery_row = await session.scalar(
            select(Delivery).where(Delivery.reward_session_id == reward.id)
        )

    assert reward_row is not None
    assert reward_row.status == "rewarded"
    assert delivery_row is not None
    assert delivery_row.status == "pending"
    assert delivery_row.attempts == 1

    retried = await delivery.deliver(reward.id)

    assert retried.status == "delivered"
    assert len(bot.copies) == 2



@pytest.mark.asyncio
async def test_stale_sending_state_recovers_to_rewarded(setup) -> None:
    database, _bot, delivery, reward, _quality_id = setup

    result = await delivery._prepare(reward.id)
    assert not hasattr(result, "status")

    async with database.session() as session, session.begin():
        delivery_row = await session.scalar(
            select(Delivery).where(Delivery.reward_session_id == reward.id)
        )
        reward_row = await session.get(RewardSession, reward.id)
        assert delivery_row is not None
        assert reward_row is not None
        delivery_row.status = "sending"
        delivery_row.send_started_at = datetime.now(UTC) - timedelta(minutes=10)
        reward_row.status = "delivering"
        reward_row.delivery_started_at = datetime.now(UTC) - timedelta(minutes=10)

    recovered = await delivery.recover_stale_sends(stale_seconds=60)

    async with database.session() as session:
        delivery_row = await session.scalar(
            select(Delivery).where(Delivery.reward_session_id == reward.id)
        )
        reward_row = await session.get(RewardSession, reward.id)

    assert recovered == 1
    assert delivery_row is not None
    assert delivery_row.status == "pending"
    assert delivery_row.send_started_at is None
    assert reward_row is not None
    assert reward_row.status == "rewarded"
    assert reward_row.delivery_started_at is None



@pytest.mark.asyncio
async def test_delivery_caption_entities_are_passed_to_copy_message(setup) -> None:
    database, bot, delivery, reward, _quality_id = setup
    body = "%movie% %quality%"
    movie_token_len = len("%movie%".encode("utf-16-le")) // 2
    entity = MessageEntity(
        type=MessageEntityType.BOLD,
        offset=0,
        length=movie_token_len,
    )

    async with database.session() as session, session.begin():
        session.add(
            MessageTemplate(
                key="delivery_caption",
                body=body,
                entities=serialize_entities([entity]),
            )
        )

    result = await delivery.deliver(reward.id)

    assert result.status == "delivered"
    assert bot.copies
    call = bot.copies[0]
    assert call["caption"] == "Top Gun 720p"
    assert call["caption_entities"] is not None
    assert len(call["caption_entities"]) == 1
    assert call["caption_entities"][0].type == MessageEntityType.BOLD
    assert call["caption_entities"][0].length == (
        len("Top Gun".encode("utf-16-le")) // 2
    )
