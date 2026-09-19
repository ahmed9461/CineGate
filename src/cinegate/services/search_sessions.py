from __future__ import annotations

import secrets
from dataclasses import dataclass

from sqlalchemy import select, update

from cinegate.db.models import UserSearchSession
from cinegate.db.session import Database


@dataclass(frozen=True, slots=True)
class SearchSessionSnapshot:
    telegram_user_id: int
    nonce: str
    raw_query: str
    normalized_query: str
    result_movie_ids: tuple[int, ...]
    state: str
    selected_movie_id: int | None
    result_message_id: int | None
    poster_message_id: int | None


@dataclass(frozen=True, slots=True)
class SearchSessionReplacement:
    session: SearchSessionSnapshot
    previous_result_message_id: int | None
    previous_poster_message_id: int | None


class SearchSessionService:
    """Durable single-current-search UI state per Telegram user."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def replace(
        self,
        *,
        telegram_user_id: int,
        raw_query: str,
        normalized_query: str,
        result_movie_ids: tuple[int, ...],
    ) -> SearchSessionReplacement:
        nonce = secrets.token_urlsafe(6)

        async with self._database.session() as session, session.begin():
            current = await session.scalar(
                select(UserSearchSession)
                .where(UserSearchSession.telegram_user_id == telegram_user_id)
                .with_for_update()
            )

            previous_result = current.result_message_id if current else None
            previous_poster = current.poster_message_id if current else None

            if current is None:
                current = UserSearchSession(
                    telegram_user_id=telegram_user_id,
                    nonce=nonce,
                    raw_query=raw_query,
                    normalized_query=normalized_query,
                    result_movie_ids=list(result_movie_ids),
                    state="results",
                )
                session.add(current)
            else:
                current.nonce = nonce
                current.raw_query = raw_query
                current.normalized_query = normalized_query
                current.result_movie_ids = list(result_movie_ids)
                current.state = "results"
                current.selected_movie_id = None
                current.result_message_id = None
                current.poster_message_id = None

            await session.flush()
            snapshot = _snapshot(current)

        return SearchSessionReplacement(
            session=snapshot,
            previous_result_message_id=previous_result,
            previous_poster_message_id=previous_poster,
        )

    async def get_current(
        self,
        *,
        telegram_user_id: int,
        nonce: str,
    ) -> SearchSessionSnapshot | None:
        async with self._database.session() as session:
            current = await session.scalar(
                select(UserSearchSession).where(
                    UserSearchSession.telegram_user_id == telegram_user_id,
                    UserSearchSession.nonce == nonce,
                )
            )
            return _snapshot(current) if current is not None else None

    async def set_result_message(
        self,
        *,
        telegram_user_id: int,
        nonce: str,
        message_id: int,
    ) -> bool:
        async with self._database.session() as session, session.begin():
            changed = await session.scalar(
                update(UserSearchSession)
                .where(
                    UserSearchSession.telegram_user_id == telegram_user_id,
                    UserSearchSession.nonce == nonce,
                    UserSearchSession.state == "results",
                )
                .values(result_message_id=message_id)
                .returning(UserSearchSession.telegram_user_id)
            )
            return changed is not None

    async def claim_movie(
        self,
        *,
        telegram_user_id: int,
        nonce: str,
        movie_id: int,
    ) -> SearchSessionSnapshot | None:
        async with self._database.session() as session, session.begin():
            current = await session.scalar(
                select(UserSearchSession)
                .where(UserSearchSession.telegram_user_id == telegram_user_id)
                .with_for_update()
            )
            if (
                current is None
                or current.nonce != nonce
                or current.state != "results"
                or movie_id not in current.result_movie_ids
            ):
                return None

            current.state = "opening"
            current.selected_movie_id = movie_id
            await session.flush()
            return _snapshot(current)

    async def complete_movie(
        self,
        *,
        telegram_user_id: int,
        nonce: str,
        movie_id: int,
        poster_message_id: int,
    ) -> bool:
        async with self._database.session() as session, session.begin():
            changed = await session.scalar(
                update(UserSearchSession)
                .where(
                    UserSearchSession.telegram_user_id == telegram_user_id,
                    UserSearchSession.nonce == nonce,
                    UserSearchSession.state == "opening",
                    UserSearchSession.selected_movie_id == movie_id,
                )
                .values(
                    state="movie",
                    poster_message_id=poster_message_id,
                    result_message_id=None,
                )
                .returning(UserSearchSession.telegram_user_id)
            )
            return changed is not None

    async def reset_opening(
        self,
        *,
        telegram_user_id: int,
        nonce: str,
        movie_id: int,
    ) -> bool:
        async with self._database.session() as session, session.begin():
            changed = await session.scalar(
                update(UserSearchSession)
                .where(
                    UserSearchSession.telegram_user_id == telegram_user_id,
                    UserSearchSession.nonce == nonce,
                    UserSearchSession.state == "opening",
                    UserSearchSession.selected_movie_id == movie_id,
                )
                .values(
                    state="results",
                    selected_movie_id=None,
                )
                .returning(UserSearchSession.telegram_user_id)
            )
            return changed is not None

    async def claim_back(
        self,
        *,
        telegram_user_id: int,
        nonce: str,
    ) -> SearchSessionSnapshot | None:
        async with self._database.session() as session, session.begin():
            current = await session.scalar(
                select(UserSearchSession)
                .where(UserSearchSession.telegram_user_id == telegram_user_id)
                .with_for_update()
            )
            if (
                current is None
                or current.nonce != nonce
                or current.state != "movie"
            ):
                return None

            current.state = "returning"
            await session.flush()
            return _snapshot(current)

    async def complete_back(
        self,
        *,
        telegram_user_id: int,
        nonce: str,
        result_message_id: int,
    ) -> bool:
        async with self._database.session() as session, session.begin():
            changed = await session.scalar(
                update(UserSearchSession)
                .where(
                    UserSearchSession.telegram_user_id == telegram_user_id,
                    UserSearchSession.nonce == nonce,
                    UserSearchSession.state == "returning",
                )
                .values(
                    state="results",
                    selected_movie_id=None,
                    result_message_id=result_message_id,
                    poster_message_id=None,
                )
                .returning(UserSearchSession.telegram_user_id)
            )
            return changed is not None

    async def reset_returning(
        self,
        *,
        telegram_user_id: int,
        nonce: str,
    ) -> bool:
        async with self._database.session() as session, session.begin():
            changed = await session.scalar(
                update(UserSearchSession)
                .where(
                    UserSearchSession.telegram_user_id == telegram_user_id,
                    UserSearchSession.nonce == nonce,
                    UserSearchSession.state == "returning",
                )
                .values(state="movie")
                .returning(UserSearchSession.telegram_user_id)
            )
            return changed is not None


def _snapshot(session: UserSearchSession) -> SearchSessionSnapshot:
    return SearchSessionSnapshot(
        telegram_user_id=session.telegram_user_id,
        nonce=session.nonce,
        raw_query=session.raw_query,
        normalized_query=session.normalized_query,
        result_movie_ids=tuple(int(value) for value in session.result_movie_ids),
        state=session.state,
        selected_movie_id=session.selected_movie_id,
        result_message_id=session.result_message_id,
        poster_message_id=session.poster_message_id,
    )
