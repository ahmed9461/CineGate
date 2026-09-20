from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select

from cinegate.db.models import (
    AdminAuditLog,
    Delivery,
    Movie,
    MovieQuality,
    RewardSession,
)
from cinegate.db.session import Database

_ACTIVE_REWARD_STATUSES = (
    "pending",
    "client_completed",
    "provider_confirmed",
    "rewarded",
    "delivering",
)


@dataclass(frozen=True, slots=True)
class ProblemMovie:
    movie_id: int
    title: str
    status: str
    poster_message_id: int


@dataclass(frozen=True, slots=True)
class FailedDeletion:
    delivery_id: int
    telegram_user_id: int
    telegram_message_id: int | None
    last_error: str | None


@dataclass(frozen=True, slots=True)
class RecentAudit:
    audit_id: int
    owner_user_id: int
    action: str
    target_type: str
    target_key: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class DiagnosticsSnapshot:
    indexed_movies: int
    pending_movies: int
    orphan_movies: int
    ambiguous_movies: int
    qualities: int
    active_rewards: int
    rewarded_waiting_delivery: int
    sent_waiting_delete: int
    delete_failed: int
    audit_entries: int
    problem_movies: tuple[ProblemMovie, ...]
    failed_deletions: tuple[FailedDeletion, ...]
    recent_audits: tuple[RecentAudit, ...]


class AdminDiagnosticsService:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def snapshot(self, *, problem_limit: int = 5) -> DiagnosticsSnapshot:
        problem_limit = max(1, min(20, problem_limit))

        async with self._database.session() as session:
            movie_counts = (
                await session.execute(
                    select(
                        func.count().filter(Movie.status == "indexed"),
                        func.count().filter(Movie.status == "pending"),
                        func.count().filter(Movie.status == "orphan"),
                        func.count().filter(Movie.status == "ambiguous"),
                    )
                )
            ).one()

            quality_count = int(
                await session.scalar(select(func.count(MovieQuality.id))) or 0
            )
            reward_counts = (
                await session.execute(
                    select(
                        func.count().filter(
                            RewardSession.status.in_(_ACTIVE_REWARD_STATUSES)
                        ),
                        func.count().filter(RewardSession.status == "rewarded"),
                    )
                )
            ).one()
            delivery_counts = (
                await session.execute(
                    select(
                        func.count().filter(Delivery.status == "sent"),
                        func.count().filter(Delivery.status == "delete_failed"),
                    )
                )
            ).one()

            movies = (
                await session.execute(
                    select(
                        Movie.id,
                        Movie.display_title,
                        Movie.status,
                        Movie.poster_message_id,
                    )
                    .where(Movie.status.in_(("orphan", "ambiguous")))
                    .order_by(Movie.updated_at.desc(), Movie.id.desc())
                    .limit(problem_limit)
                )
            ).all()

            audit_count = int(
                await session.scalar(select(func.count(AdminAuditLog.id))) or 0
            )

            audits = (
                await session.execute(
                    select(
                        AdminAuditLog.id,
                        AdminAuditLog.owner_user_id,
                        AdminAuditLog.action,
                        AdminAuditLog.target_type,
                        AdminAuditLog.target_key,
                        AdminAuditLog.created_at,
                    )
                    .order_by(
                        AdminAuditLog.created_at.desc(),
                        AdminAuditLog.id.desc(),
                    )
                    .limit(problem_limit)
                )
            ).all()

            failures = (
                await session.execute(
                    select(
                        Delivery.id,
                        Delivery.telegram_user_id,
                        Delivery.telegram_message_id,
                        Delivery.last_error,
                    )
                    .where(Delivery.status == "delete_failed")
                    .order_by(Delivery.updated_at.desc(), Delivery.id.desc())
                    .limit(problem_limit)
                )
            ).all()

        return DiagnosticsSnapshot(
            indexed_movies=int(movie_counts[0] or 0),
            pending_movies=int(movie_counts[1] or 0),
            orphan_movies=int(movie_counts[2] or 0),
            ambiguous_movies=int(movie_counts[3] or 0),
            qualities=quality_count,
            active_rewards=int(reward_counts[0] or 0),
            rewarded_waiting_delivery=int(reward_counts[1] or 0),
            sent_waiting_delete=int(delivery_counts[0] or 0),
            delete_failed=int(delivery_counts[1] or 0),
            audit_entries=audit_count,
            problem_movies=tuple(
                ProblemMovie(
                    movie_id=row.id,
                    title=row.display_title,
                    status=row.status,
                    poster_message_id=row.poster_message_id,
                )
                for row in movies
            ),
            failed_deletions=tuple(
                FailedDeletion(
                    delivery_id=row.id,
                    telegram_user_id=row.telegram_user_id,
                    telegram_message_id=row.telegram_message_id,
                    last_error=row.last_error,
                )
                for row in failures
            ),
            recent_audits=tuple(
                RecentAudit(
                    audit_id=row.id,
                    owner_user_id=row.owner_user_id,
                    action=row.action,
                    target_type=row.target_type,
                    target_key=row.target_key,
                    created_at=row.created_at,
                )
                for row in audits
            ),
        )
