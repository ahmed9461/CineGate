from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import func, select, update

from cinegate.db.models import Delivery, Movie, MovieQuality, RewardSession
from cinegate.db.session import Database
from cinegate.domain.delivery import DeliveryResult, DueDeletion, RewardNotReady
from cinegate.presentation.delivery import (
    DEFAULT_DELIVERY_CAPTION,
    DeliveryTemplateError,
    render_delivery_caption,
)
from cinegate.repositories.settings import SettingsRepository
from cinegate.repositories.templates import MessageTemplateRepository

_DEFAULT_DELETE_SECONDS = 120
_MIN_DELETE_SECONDS = 5
_MAX_DELETE_SECONDS = 172000
_MAX_ERROR_LENGTH = 1000


@dataclass(frozen=True, slots=True)
class _PreparedDelivery:
    delivery_id: int
    telegram_user_id: int
    archive_channel_id: int
    archive_message_id: int
    caption: str
    delete_seconds: int


class DeliveryService:
    """Copy rewarded qualities and maintain durable deletion state."""

    def __init__(self, database: Database, bot: Bot) -> None:
        self._database = database
        self._bot = bot

    async def deliver(self, reward_session_id: UUID) -> DeliveryResult:
        prepared_or_result = await self._prepare(reward_session_id)
        if isinstance(prepared_or_result, DeliveryResult):
            return prepared_or_result

        prepared = prepared_or_result
        try:
            copied = await self._bot.copy_message(
                chat_id=prepared.telegram_user_id,
                from_chat_id=prepared.archive_channel_id,
                message_id=prepared.archive_message_id,
                caption=prepared.caption,
                protect_content=False,
            )
        except TelegramAPIError as exc:
            await self._reset_failed_send(
                reward_session_id=reward_session_id,
                delivery_id=prepared.delivery_id,
                error=str(exc),
            )
            return DeliveryResult(status="retryable")

        return await self._finalize_sent(
            reward_session_id=reward_session_id,
            delivery_id=prepared.delivery_id,
            telegram_message_id=copied.message_id,
            delete_seconds=prepared.delete_seconds,
        )

    async def _prepare(
        self,
        reward_session_id: UUID,
    ) -> _PreparedDelivery | DeliveryResult:
        now = _utcnow()

        async with self._database.session() as session, session.begin():
            reward = await session.scalar(
                select(RewardSession)
                .where(RewardSession.id == reward_session_id)
                .with_for_update()
            )
            if reward is None:
                raise RewardNotReady("reward session does not exist")

            delivery = await session.scalar(
                select(Delivery)
                .where(Delivery.reward_session_id == reward.id)
                .with_for_update()
            )

            if reward.status == "delivered":
                if delivery is None:
                    raise RewardNotReady("delivered reward has no delivery record")
                return DeliveryResult(
                    status="delivered",
                    telegram_message_id=delivery.telegram_message_id,
                    delete_at=delivery.delete_at,
                )
            if reward.status == "delivering":
                return DeliveryResult(status="processing")
            if reward.status != "rewarded":
                raise RewardNotReady("reward is not ready for delivery")

            quality = await session.get(MovieQuality, reward.movie_quality_id)
            movie = await session.get(Movie, reward.movie_id)
            if quality is None or movie is None:
                raise RewardNotReady("rewarded movie quality no longer exists")

            settings = await SettingsRepository(session).get_many(
                ("movie_delete_seconds",)
            )
            delete_seconds = _bounded_delete_seconds(
                settings.get("movie_delete_seconds")
            )
            template = await MessageTemplateRepository(session).get_body(
                "delivery_caption",
                DEFAULT_DELIVERY_CAPTION,
            )
            try:
                caption = render_delivery_caption(
                    template,
                    movie=movie.display_title,
                    year=movie.year,
                    quality=quality.quality,
                    delete_seconds=delete_seconds,
                )
            except DeliveryTemplateError:
                caption = render_delivery_caption(
                    DEFAULT_DELIVERY_CAPTION,
                    movie=movie.display_title,
                    year=movie.year,
                    quality=quality.quality,
                    delete_seconds=delete_seconds,
                )

            if delivery is None:
                delivery = Delivery(
                    reward_session_id=reward.id,
                    telegram_user_id=reward.telegram_user_id,
                    movie_quality_id=quality.id,
                    status="pending",
                )
                session.add(delivery)
                await session.flush()

            if delivery.status in {"sent", "deleted"}:
                reward.status = "delivered"
                if reward.delivered_at is None:
                    reward.delivered_at = delivery.sent_at or now
                return DeliveryResult(
                    status="delivered",
                    telegram_message_id=delivery.telegram_message_id,
                    delete_at=delivery.delete_at,
                )
            if delivery.status == "sending":
                reward.status = "delivering"
                return DeliveryResult(status="processing")

            reward.status = "delivering"
            reward.delivery_started_at = now
            delivery.status = "sending"
            delivery.send_started_at = now
            delivery.last_error = None

            return _PreparedDelivery(
                delivery_id=delivery.id,
                telegram_user_id=reward.telegram_user_id,
                archive_channel_id=quality.archive_channel_id,
                archive_message_id=quality.archive_message_id,
                caption=caption,
                delete_seconds=delete_seconds,
            )

    async def _reset_failed_send(
        self,
        *,
        reward_session_id: UUID,
        delivery_id: int,
        error: str,
    ) -> None:
        async with self._database.session() as session, session.begin():
            reward = await session.scalar(
                select(RewardSession)
                .where(RewardSession.id == reward_session_id)
                .with_for_update()
            )
            delivery = await session.scalar(
                select(Delivery)
                .where(Delivery.id == delivery_id)
                .with_for_update()
            )
            if reward is None or delivery is None:
                return

            if reward.status == "delivering":
                reward.status = "rewarded"
                reward.delivery_started_at = None
            if delivery.status == "sending":
                delivery.status = "pending"
                delivery.send_started_at = None
                delivery.attempts += 1
                delivery.last_error = error[:_MAX_ERROR_LENGTH]

    async def _finalize_sent(
        self,
        *,
        reward_session_id: UUID,
        delivery_id: int,
        telegram_message_id: int,
        delete_seconds: int,
    ) -> DeliveryResult:
        now = _utcnow()
        delete_at = now + timedelta(seconds=delete_seconds)

        async with self._database.session() as session, session.begin():
            reward = await session.scalar(
                select(RewardSession)
                .where(RewardSession.id == reward_session_id)
                .with_for_update()
            )
            delivery = await session.scalar(
                select(Delivery)
                .where(Delivery.id == delivery_id)
                .with_for_update()
            )
            if reward is None or delivery is None:
                raise RewardNotReady("delivery state disappeared after Telegram copy")

            if delivery.status == "sent":
                return DeliveryResult(
                    status="delivered",
                    telegram_message_id=delivery.telegram_message_id,
                    delete_at=delivery.delete_at,
                )

            delivery.status = "sent"
            delivery.telegram_message_id = telegram_message_id
            delivery.sent_at = now
            delivery.delete_at = delete_at
            delivery.next_attempt_at = delete_at
            delivery.send_started_at = None
            delivery.last_error = None

            reward.status = "delivered"
            reward.delivered_at = now
            reward.delivery_started_at = None

            return DeliveryResult(
                status="delivered",
                telegram_message_id=telegram_message_id,
                delete_at=delete_at,
            )

    async def recover_stale_sends(self, *, stale_seconds: int = 300) -> int:
        if stale_seconds <= 0:
            raise ValueError("stale_seconds must be positive")

        cutoff = _utcnow() - timedelta(seconds=stale_seconds)
        async with self._database.session() as session, session.begin():
            deliveries = (
                await session.execute(
                    select(Delivery)
                    .where(
                        Delivery.status == "sending",
                        Delivery.send_started_at.is_not(None),
                        Delivery.send_started_at <= cutoff,
                    )
                    .with_for_update(skip_locked=True)
                )
            ).scalars().all()

            recovered = 0
            for delivery in deliveries:
                reward = await session.scalar(
                    select(RewardSession)
                    .where(RewardSession.id == delivery.reward_session_id)
                    .with_for_update()
                )
                delivery.status = "pending"
                delivery.send_started_at = None
                delivery.attempts += 1
                delivery.last_error = "recovered stale sending state"
                if reward is not None and reward.status == "delivering":
                    reward.status = "rewarded"
                    reward.delivery_started_at = None
                recovered += 1
            return recovered

    async def recover_stale_deletions(self, *, stale_seconds: int = 300) -> int:
        if stale_seconds <= 0:
            raise ValueError("stale_seconds must be positive")

        cutoff = _utcnow() - timedelta(seconds=stale_seconds)
        async with self._database.session() as session, session.begin():
            result = await session.execute(
                update(Delivery)
                .where(
                    Delivery.status == "deleting",
                    Delivery.delete_started_at.is_not(None),
                    Delivery.delete_started_at <= cutoff,
                )
                .values(
                    status="sent",
                    delete_started_at=None,
                    next_attempt_at=func.now(),
                )
                .returning(Delivery.id)
            )
            return len(result.scalars().all())

    async def claim_due_deletions(self, *, limit: int = 50) -> tuple[DueDeletion, ...]:
        limit = max(1, min(100, limit))
        now = _utcnow()

        async with self._database.session() as session, session.begin():
            rows = (
                await session.execute(
                    select(Delivery)
                    .where(
                        Delivery.status == "sent",
                        Delivery.telegram_message_id.is_not(None),
                        Delivery.next_attempt_at.is_not(None),
                        Delivery.next_attempt_at <= now,
                    )
                    .order_by(Delivery.next_attempt_at, Delivery.id)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).scalars().all()

            tasks: list[DueDeletion] = []
            for delivery in rows:
                delivery.status = "deleting"
                delivery.delete_started_at = now
                tasks.append(
                    DueDeletion(
                        delivery_id=delivery.id,
                        telegram_user_id=delivery.telegram_user_id,
                        telegram_message_id=int(delivery.telegram_message_id),
                        attempts=delivery.attempts,
                    )
                )
            return tuple(tasks)

    async def mark_deleted(self, delivery_id: int) -> None:
        now = _utcnow()
        async with self._database.session() as session, session.begin():
            await session.execute(
                update(Delivery)
                .where(
                    Delivery.id == delivery_id,
                    Delivery.status == "deleting",
                )
                .values(
                    status="deleted",
                    deleted_at=now,
                    delete_started_at=None,
                    next_attempt_at=None,
                    last_error=None,
                )
            )

    async def reschedule_delete(self, delivery_id: int, error: str) -> None:
        now = _utcnow()
        async with self._database.session() as session, session.begin():
            delivery = await session.scalar(
                select(Delivery)
                .where(
                    Delivery.id == delivery_id,
                    Delivery.status == "deleting",
                )
                .with_for_update()
            )
            if delivery is None:
                return

            attempts = delivery.attempts + 1
            backoff_seconds = min(300, 5 * (2 ** min(attempts - 1, 6)))
            delivery.status = "sent"
            delivery.attempts = attempts
            delivery.last_error = error[:_MAX_ERROR_LENGTH]
            delivery.delete_started_at = None
            delivery.next_attempt_at = now + timedelta(seconds=backoff_seconds)


def _bounded_delete_seconds(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return _DEFAULT_DELETE_SECONDS
    return max(_MIN_DELETE_SECONDS, min(_MAX_DELETE_SECONDS, value))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
