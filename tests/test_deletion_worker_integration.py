from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
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
from cinegate.domain.delivery import DueDeletion
from cinegate.services.delivery import DeliveryService
from cinegate.workers.deletion import DeliveryDeletionWorker

DATABASE_URL = os.getenv("CINEGATE_DATABASE_URL")
ARCHIVE_CHANNEL_ID = -1001234567890
USER_ID = 123456789


class FakeTelegramFailure(TelegramAPIError):
    def __init__(self, message: str = "temporary failure") -> None:
        Exception.__init__(self, message)
        self.message = message
        self.method = None


class FakeTelegramBadRequest(TelegramBadRequest):
    def __init__(self, message: str = "message to delete not found") -> None:
        Exception.__init__(self, message)
        self.message = message
        self.method = None


class FakeBot:
    def __init__(self) -> None:
        self.deleted: list[tuple[int, int]] = []
        self.mode = "ok"

    async def delete_message(self, *, chat_id: int, message_id: int):
        self.deleted.append((chat_id, message_id))
        if self.mode == "missing":
            raise FakeTelegramBadRequest()
        if self.mode == "transient":
            raise FakeTelegramFailure()
        return True


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

    database = Database(DATABASE_URL, pool_size=4, max_overflow=0)
    await clean_database(database)

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

        quality = MovieQuality(
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
        session.add(quality)
        await session.flush()

        reward = RewardSession(
            telegram_user_id=USER_ID,
            movie_id=movie.id,
            movie_quality_id=quality.id,
            quality="720p",
            status="delivered",
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
            rewarded_at=datetime.now(UTC),
            delivered_at=datetime.now(UTC),
        )
        session.add(reward)
        await session.flush()

        due = Delivery(
            reward_session_id=reward.id,
            telegram_user_id=USER_ID,
            movie_quality_id=quality.id,
            status="sent",
            telegram_message_id=8000,
            sent_at=datetime.now(UTC) - timedelta(minutes=1),
            delete_at=datetime.now(UTC) - timedelta(seconds=1),
            next_attempt_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        session.add(due)
        await session.flush()
        delivery_id = due.id

    bot = FakeBot()
    service = DeliveryService(database, bot)  # type: ignore[arg-type]

    try:
        yield database, bot, service, delivery_id
    finally:
        await clean_database(database)
        await database.dispose()


@pytest.mark.asyncio
async def test_due_delivery_is_claimed_and_marked_deleted(setup) -> None:
    database, bot, service, delivery_id = setup
    worker = DeliveryDeletionWorker(
        delivery_service=service,
        bot=bot,  # type: ignore[arg-type]
    )

    due = await service.claim_due_deletions(limit=10)

    assert len(due) == 1
    assert due[0].delivery_id == delivery_id

    await worker._delete_one(due[0])

    async with database.session() as session:
        row = await session.get(Delivery, delivery_id)

    assert bot.deleted == [(USER_ID, 8000)]
    assert row is not None
    assert row.status == "deleted"
    assert row.deleted_at is not None


@pytest.mark.asyncio
async def test_not_yet_due_delivery_is_untouched(setup) -> None:
    database, _bot, service, delivery_id = setup

    async with database.session() as session, session.begin():
        row = await session.get(Delivery, delivery_id)
        assert row is not None
        row.next_attempt_at = datetime.now(UTC) + timedelta(minutes=5)

    due = await service.claim_due_deletions(limit=10)

    assert due == ()


@pytest.mark.asyncio
async def test_already_missing_message_is_considered_deleted(setup) -> None:
    database, bot, service, delivery_id = setup
    bot.mode = "missing"
    worker = DeliveryDeletionWorker(
        delivery_service=service,
        bot=bot,  # type: ignore[arg-type]
    )
    due = await service.claim_due_deletions(limit=10)

    await worker._delete_one(due[0])

    async with database.session() as session:
        row = await session.get(Delivery, delivery_id)

    assert row is not None
    assert row.status == "deleted"


@pytest.mark.asyncio
async def test_transient_delete_failure_is_rescheduled_with_backoff(setup) -> None:
    database, bot, service, delivery_id = setup
    bot.mode = "transient"
    worker = DeliveryDeletionWorker(
        delivery_service=service,
        bot=bot,  # type: ignore[arg-type]
    )
    due = await service.claim_due_deletions(limit=10)
    before = datetime.now(UTC)

    await worker._delete_one(due[0])

    async with database.session() as session:
        row = await session.get(Delivery, delivery_id)

    assert row is not None
    assert row.status == "sent"
    assert row.attempts == 1
    assert row.next_attempt_at is not None
    assert row.next_attempt_at > before
    assert row.last_error is not None


@pytest.mark.asyncio
async def test_stale_deleting_state_is_recovered_after_restart(setup) -> None:
    database, _bot, service, delivery_id = setup

    async with database.session() as session, session.begin():
        row = await session.get(Delivery, delivery_id)
        assert row is not None
        row.status = "deleting"
        row.delete_started_at = datetime.now(UTC) - timedelta(minutes=10)
        row.next_attempt_at = None

    recovered = await service.recover_stale_deletions(stale_seconds=60)

    async with database.session() as session:
        row = await session.get(Delivery, delivery_id)

    assert recovered == 1
    assert row is not None
    assert row.status == "sent"
    assert row.delete_started_at is None
    assert row.next_attempt_at is not None


@pytest.mark.asyncio
async def test_two_claimers_cannot_claim_same_due_delivery(setup) -> None:
    _database, _bot, service, _delivery_id = setup
    second_service = DeliveryService(service._database, service._bot)

    first, second = await asyncio.gather(
        service.claim_due_deletions(limit=10),
        second_service.claim_due_deletions(limit=10),
    )

    assert sorted((len(first), len(second))) == [0, 1]


@pytest.mark.asyncio
async def test_claim_batch_is_bounded(setup) -> None:
    database, _bot, service, delivery_id = setup

    async with database.session() as session, session.begin():
        base = await session.get(Delivery, delivery_id)
        assert base is not None
        reward = await session.get(RewardSession, base.reward_session_id)
        assert reward is not None
        quality_id = base.movie_quality_id

        for offset in range(1, 6):
            extra_reward = RewardSession(
                telegram_user_id=USER_ID + offset,
                movie_id=reward.movie_id,
                movie_quality_id=quality_id,
                quality="720p",
                status="delivered",
                expires_at=datetime.now(UTC) + timedelta(minutes=10),
                rewarded_at=datetime.now(UTC),
                delivered_at=datetime.now(UTC),
            )
            session.add(extra_reward)
            await session.flush()
            session.add(
                Delivery(
                    reward_session_id=extra_reward.id,
                    telegram_user_id=USER_ID + offset,
                    movie_quality_id=quality_id,
                    status="sent",
                    telegram_message_id=8000 + offset,
                    sent_at=datetime.now(UTC),
                    delete_at=datetime.now(UTC) - timedelta(seconds=1),
                    next_attempt_at=datetime.now(UTC) - timedelta(seconds=1),
                )
            )

    due = await service.claim_due_deletions(limit=3)

    assert len(due) == 3
    assert all(isinstance(item, DueDeletion) for item in due)
