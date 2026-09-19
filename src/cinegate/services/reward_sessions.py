from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select, update

from cinegate.db.models import Movie, MovieQuality, RewardSession
from cinegate.db.session import Database
from cinegate.domain.rewards import (
    ActiveRewardConflict,
    RewardQualityUnavailable,
    RewardSessionExpired,
    RewardSessionNotFound,
    RewardSessionView,
    RewardUserMismatch,
)
from cinegate.repositories.settings import SettingsRepository

_ACTIVE_STATUSES = (
    "pending",
    "client_completed",
    "provider_confirmed",
    "rewarded",
    "delivering",
)
_DEFAULT_SESSION_SECONDS = 600
_MIN_SESSION_SECONDS = 60
_MAX_SESSION_SECONDS = 3600
_PROMPT_CLAIM_SECONDS = 30


class RewardSessionService:
    """Durable exact user/movie/quality reward state machine."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def get_or_create(
        self,
        *,
        telegram_user_id: int,
        movie_id: int,
        quality: str,
    ) -> tuple[RewardSessionView, bool]:
        now = _utcnow()

        async with self._database.session() as session, session.begin():
            await session.execute(
                select(func.pg_advisory_xact_lock(telegram_user_id))
            )

            quality_row = await session.scalar(
                select(MovieQuality)
                .join(Movie, Movie.id == MovieQuality.movie_id)
                .where(
                    MovieQuality.movie_id == movie_id,
                    MovieQuality.quality == quality,
                    Movie.status == "indexed",
                )
            )
            if quality_row is None:
                raise RewardQualityUnavailable("selected quality is unavailable")

            await session.execute(
                update(RewardSession)
                .where(
                    RewardSession.telegram_user_id == telegram_user_id,
                    RewardSession.status.in_(_ACTIVE_STATUSES),
                    RewardSession.expires_at <= now,
                )
                .values(status="expired")
            )

            active = await session.scalar(
                select(RewardSession)
                .where(
                    RewardSession.telegram_user_id == telegram_user_id,
                    RewardSession.status.in_(_ACTIVE_STATUSES),
                )
                .order_by(RewardSession.created_at.desc())
                .limit(1)
                .with_for_update()
            )

            if active is not None:
                view = _view(active)
                if (
                    active.movie_id == movie_id
                    and active.movie_quality_id == quality_row.id
                ):
                    return view, False
                raise ActiveRewardConflict(view)

            ttl = await SettingsRepository(session).get_int(
                "reward_session_seconds"
            )
            ttl = _bounded_session_seconds(ttl)

            reward = RewardSession(
                telegram_user_id=telegram_user_id,
                movie_id=movie_id,
                movie_quality_id=quality_row.id,
                quality=quality_row.quality,
                status="pending",
                expires_at=now + timedelta(seconds=ttl),
            )
            session.add(reward)
            await session.flush()
            return _view(reward), True

    async def get(self, session_id: UUID) -> RewardSessionView:
        async with self._database.session() as session, session.begin():
            reward = await session.scalar(
                select(RewardSession)
                .where(RewardSession.id == session_id)
                .with_for_update()
            )
            reward = await self._require_current(reward, now=_utcnow())
            return _view(reward)

    async def claim_prompt(
        self,
        *,
        session_id: UUID,
        telegram_user_id: int,
    ) -> bool:
        now = _utcnow()
        stale_before = now - timedelta(seconds=_PROMPT_CLAIM_SECONDS)

        async with self._database.session() as session, session.begin():
            reward = await session.scalar(
                select(RewardSession)
                .where(RewardSession.id == session_id)
                .with_for_update()
            )
            reward = await self._require_current(reward, now=now)
            _require_user(reward, telegram_user_id)

            if reward.prompt_message_id is not None:
                return False
            if (
                reward.prompt_claimed_at is not None
                and reward.prompt_claimed_at > stale_before
            ):
                return False

            reward.prompt_claimed_at = now
            return True

    async def complete_prompt(
        self,
        *,
        session_id: UUID,
        telegram_user_id: int,
        message_id: int,
    ) -> bool:
        async with self._database.session() as session, session.begin():
            reward = await session.scalar(
                select(RewardSession)
                .where(RewardSession.id == session_id)
                .with_for_update()
            )
            reward = await self._require_current(reward, now=_utcnow())
            _require_user(reward, telegram_user_id)

            if reward.prompt_message_id is not None:
                return reward.prompt_message_id == message_id

            reward.prompt_message_id = message_id
            reward.prompt_claimed_at = None
            return True

    async def reset_prompt_claim(
        self,
        *,
        session_id: UUID,
        telegram_user_id: int,
    ) -> None:
        async with self._database.session() as session, session.begin():
            reward = await session.scalar(
                select(RewardSession)
                .where(RewardSession.id == session_id)
                .with_for_update()
            )
            if reward is None or reward.telegram_user_id != telegram_user_id:
                return
            if reward.prompt_message_id is None:
                reward.prompt_claimed_at = None

    async def mark_client_completed(
        self,
        *,
        session_id: UUID,
        telegram_user_id: int,
    ) -> RewardSessionView:
        now = _utcnow()

        async with self._database.session() as session, session.begin():
            reward = await session.scalar(
                select(RewardSession)
                .where(RewardSession.id == session_id)
                .with_for_update()
            )
            reward = await self._require_current(reward, now=now)
            _require_user(reward, telegram_user_id)

            if reward.client_completed_at is None:
                reward.client_completed_at = now
            _refresh_reward_status(reward, now)
            return _view(reward)

    async def mark_provider_confirmed(
        self,
        *,
        telegram_user_id: int,
    ) -> RewardSessionView | None:
        now = _utcnow()

        async with self._database.session() as session, session.begin():
            await session.execute(
                select(func.pg_advisory_xact_lock(telegram_user_id))
            )
            await session.execute(
                update(RewardSession)
                .where(
                    RewardSession.telegram_user_id == telegram_user_id,
                    RewardSession.status.in_(_ACTIVE_STATUSES),
                    RewardSession.expires_at <= now,
                )
                .values(status="expired")
            )

            reward = await session.scalar(
                select(RewardSession)
                .where(
                    RewardSession.telegram_user_id == telegram_user_id,
                    RewardSession.status.in_(_ACTIVE_STATUSES),
                )
                .order_by(RewardSession.created_at.desc())
                .limit(1)
                .with_for_update()
            )
            if reward is None:
                return None

            if reward.provider_confirmed_at is None:
                reward.provider_confirmed_at = now
            _refresh_reward_status(reward, now)
            return _view(reward)

    async def _require_current(
        self,
        reward: RewardSession | None,
        *,
        now: datetime,
    ) -> RewardSession:
        if reward is None:
            raise RewardSessionNotFound("reward session not found")
        if reward.status == "expired" or reward.expires_at <= now:
            if reward.status in _ACTIVE_STATUSES:
                reward.status = "expired"
            raise RewardSessionExpired("reward session expired")
        return reward


def _refresh_reward_status(reward: RewardSession, now: datetime) -> None:
    if reward.status in {"delivering", "delivered"}:
        return
    if (
        reward.client_completed_at is not None
        and reward.provider_confirmed_at is not None
    ):
        reward.status = "rewarded"
        if reward.rewarded_at is None:
            reward.rewarded_at = now
    elif reward.client_completed_at is not None:
        reward.status = "client_completed"
    elif reward.provider_confirmed_at is not None:
        reward.status = "provider_confirmed"
    else:
        reward.status = "pending"


def _require_user(reward: RewardSession, telegram_user_id: int) -> None:
    if reward.telegram_user_id != telegram_user_id:
        raise RewardUserMismatch("reward session belongs to another user")


def _view(reward: RewardSession) -> RewardSessionView:
    return RewardSessionView(
        id=reward.id,
        telegram_user_id=reward.telegram_user_id,
        movie_id=reward.movie_id,
        movie_quality_id=reward.movie_quality_id,
        quality=reward.quality,
        status=reward.status,
        expires_at=reward.expires_at,
        prompt_message_id=reward.prompt_message_id,
        client_completed_at=reward.client_completed_at,
        provider_confirmed_at=reward.provider_confirmed_at,
    )


def _bounded_session_seconds(value: int | None) -> int:
    if value is None:
        return _DEFAULT_SESSION_SECONDS
    return max(_MIN_SESSION_SECONDS, min(_MAX_SESSION_SECONDS, value))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
