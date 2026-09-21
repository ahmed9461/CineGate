from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from cinegate.db.models import Movie, MovieQuality
from cinegate.db.session import Database
from cinegate.domain.archive import (
    ArchiveMessage,
    GroupStatus,
    MediaKind,
    ParsedMovieGroup,
)
from cinegate.domain.indexing import ArchiveIndexResult, IndexAction
from cinegate.repositories.settings import SettingsRepository
from cinegate.services.archive_parser import ArchiveParser
from cinegate.services.text import extract_quality


class ArchiveIndexService:
    """Persist one Archive Channel message safely and idempotently."""

    def __init__(self, database: Database, *, parser: ArchiveParser | None = None) -> None:
        self._database = database
        self._parser = parser or ArchiveParser()

    async def reconcile_edit(
        self,
        *,
        channel_id: int,
        message: ArchiveMessage,
    ) -> ArchiveIndexResult:
        async with self._database.session() as session, session.begin():
            configured_channel_id = await SettingsRepository(session).get_int(
                "archive_channel_id"
            )
            if configured_channel_id is None or configured_channel_id != channel_id:
                return ArchiveIndexResult(IndexAction.IGNORED)

            existing_poster = await session.scalar(
                select(Movie)
                .where(
                    Movie.archive_channel_id == channel_id,
                    Movie.poster_message_id == message.message_id,
                )
                .with_for_update()
            )
            if existing_poster is not None:
                return await self._reconcile_poster_edit(
                    session=session,
                    movie=existing_poster,
                    message=message,
                )

            # Keep the same movie -> quality lock order used by live ingest.
            # Reversing it here can deadlock an edit against a rapid new post.
            quality_movie = await session.scalar(
                select(Movie)
                .join(MovieQuality, MovieQuality.movie_id == Movie.id)
                .where(
                    MovieQuality.archive_channel_id == channel_id,
                    MovieQuality.archive_message_id == message.message_id,
                )
                .with_for_update(of=Movie)
            )
            if quality_movie is not None:
                existing_quality = await session.scalar(
                    select(MovieQuality)
                    .where(
                        MovieQuality.movie_id == quality_movie.id,
                        MovieQuality.archive_channel_id == channel_id,
                        MovieQuality.archive_message_id == message.message_id,
                    )
                    .with_for_update()
                )
                if existing_quality is None:
                    return ArchiveIndexResult(IndexAction.IGNORED)
                return await self._reconcile_quality_edit(
                    session=session,
                    movie=quality_movie,
                    quality_row=existing_quality,
                    message=message,
                )

            if message.media_kind is MediaKind.PHOTO:
                parsed = self._parser.parse([message])
                if not parsed:
                    return ArchiveIndexResult(IndexAction.IGNORED)
                return await self._upsert_poster(
                    session=session,
                    channel_id=channel_id,
                    parsed_group=parsed[0],
                )

            if message.media_kind in {MediaKind.VIDEO, MediaKind.DOCUMENT}:
                if extract_quality(message.caption) is None:
                    return ArchiveIndexResult(IndexAction.IGNORED)
                return await self._upsert_quality(
                    session=session,
                    channel_id=channel_id,
                    message=message,
                )

            return ArchiveIndexResult(IndexAction.IGNORED)

    async def ingest(
        self,
        *,
        channel_id: int,
        message: ArchiveMessage,
    ) -> ArchiveIndexResult:
        async with self._database.session() as session, session.begin():
            configured_channel_id = await SettingsRepository(session).get_int(
                "archive_channel_id"
            )
            if configured_channel_id is None or configured_channel_id != channel_id:
                return ArchiveIndexResult(IndexAction.IGNORED)

            if message.media_kind is MediaKind.PHOTO:
                parsed = self._parser.parse([message])
                if not parsed:
                    return ArchiveIndexResult(IndexAction.IGNORED)
                return await self._upsert_poster(
                    session=session,
                    channel_id=channel_id,
                    parsed_group=parsed[0],
                )

            if message.media_kind in {MediaKind.VIDEO, MediaKind.DOCUMENT}:
                if extract_quality(message.caption) is None:
                    return ArchiveIndexResult(IndexAction.IGNORED)
                return await self._upsert_quality(
                    session=session,
                    channel_id=channel_id,
                    message=message,
                )

            return ArchiveIndexResult(IndexAction.IGNORED)

    async def _reconcile_poster_edit(
        self,
        *,
        session: AsyncSession,
        movie: Movie,
        message: ArchiveMessage,
    ) -> ArchiveIndexResult:
        if message.media_kind is not MediaKind.PHOTO:
            movie.status = "ambiguous"
            movie.raw_poster_caption = message.caption or ""
            movie.parser_confidence = 0
            return await self._result_for_movie(
                session=session,
                movie=movie,
                action=IndexAction.AMBIGUOUS,
                diagnostic="edited_poster_media_invalid",
            )

        parsed = self._parser.parse([message])
        if not parsed:
            movie.status = "ambiguous"
            movie.raw_poster_caption = message.caption or ""
            movie.parser_confidence = 0
            return await self._result_for_movie(
                session=session,
                movie=movie,
                action=IndexAction.AMBIGUOUS,
                diagnostic="edited_poster_invalid",
            )

        group = parsed[0]
        movie.display_title = group.display_title
        movie.normalized_title = group.normalized_title
        movie.year = group.year
        movie.parser_style = group.parser_style.value
        movie.raw_poster_caption = group.raw_poster_caption
        movie.parser_confidence = group.poster_confidence

        status = await self._refresh_movie_status(session, movie)
        return await self._result_for_movie(
            session=session,
            movie=movie,
            action=(
                IndexAction.AMBIGUOUS
                if status == "ambiguous"
                else IndexAction.POSTER_UPSERTED
            ),
            diagnostic=(
                "edited_poster_valid_but_quality_remains_invalid"
                if status == "ambiguous"
                else None
            ),
        )

    async def _reconcile_quality_edit(
        self,
        *,
        session: AsyncSession,
        movie: Movie,
        quality_row: MovieQuality,
        message: ArchiveMessage,
    ) -> ArchiveIndexResult:
        if message.media_kind not in {MediaKind.VIDEO, MediaKind.DOCUMENT}:
            return await self._invalidate_quality_edit(
                session=session,
                movie=movie,
                quality_row=quality_row,
                message=message,
                diagnostic="edited_quality_media_invalid",
            )

        poster = ArchiveMessage(
            message_id=movie.poster_message_id,
            media_kind=MediaKind.PHOTO,
            caption=movie.raw_poster_caption,
        )
        parsed_groups = self._parser.parse([poster, message])
        if not parsed_groups:
            return await self._invalidate_quality_edit(
                session=session,
                movie=movie,
                quality_row=quality_row,
                message=message,
                diagnostic="edited_quality_invalid",
            )

        group = parsed_groups[0]
        if group.status is GroupStatus.AMBIGUOUS or not group.qualities:
            return await self._invalidate_quality_edit(
                session=session,
                movie=movie,
                quality_row=quality_row,
                message=message,
                diagnostic="edited_quality_ambiguous",
            )

        parsed = group.qualities[0]
        if parsed.quality != quality_row.quality:
            conflict = await session.scalar(
                select(MovieQuality.id)
                .where(
                    MovieQuality.movie_id == movie.id,
                    MovieQuality.quality == parsed.quality,
                    MovieQuality.id != quality_row.id,
                )
                .limit(1)
            )
            if conflict is not None:
                quality_row.raw_caption = message.caption or ""
                quality_row.parser_confidence = 0
                movie.status = "ambiguous"
                return await self._result_for_movie(
                    session=session,
                    movie=movie,
                    action=IndexAction.AMBIGUOUS,
                    diagnostic="edited_quality_conflicts_with_existing_quality",
                )

        quality_row.quality = parsed.quality
        quality_row.raw_caption = parsed.raw_caption
        quality_row.extracted_title = parsed.raw_title
        quality_row.normalized_title = parsed.normalized_title
        quality_row.extracted_year = parsed.year
        quality_row.parser_confidence = parsed.confidence
        status = await self._refresh_movie_status(session, movie)

        return await self._result_for_movie(
            session=session,
            movie=movie,
            action=(
                IndexAction.AMBIGUOUS
                if status == "ambiguous"
                else IndexAction.QUALITY_UPSERTED
            ),
            diagnostic=(
                "edited_quality_reconciled_but_movie_remains_ambiguous"
                if status == "ambiguous"
                else "edited_quality_reconciled"
            ),
        )

    async def _invalidate_quality_edit(
        self,
        *,
        session: AsyncSession,
        movie: Movie,
        quality_row: MovieQuality,
        message: ArchiveMessage,
        diagnostic: str,
    ) -> ArchiveIndexResult:
        quality_row.raw_caption = message.caption or ""
        quality_row.extracted_title = None
        quality_row.normalized_title = None
        quality_row.extracted_year = None
        quality_row.parser_confidence = 0
        movie.status = "ambiguous"
        return await self._result_for_movie(
            session=session,
            movie=movie,
            action=IndexAction.AMBIGUOUS,
            diagnostic=diagnostic,
        )

    async def _upsert_poster(
        self,
        *,
        session: AsyncSession,
        channel_id: int,
        parsed_group: ParsedMovieGroup,
    ) -> ArchiveIndexResult:
        previous = await session.scalar(
            select(Movie)
            .where(
                Movie.archive_channel_id == channel_id,
                Movie.poster_message_id < parsed_group.poster_message_id,
            )
            .order_by(Movie.poster_message_id.desc())
            .limit(1)
            .with_for_update()
        )

        if previous is not None and previous.status == "pending":
            quality_count = await self._quality_count(session, previous.id)
            previous.status = "indexed" if quality_count else "orphan"

        statement = insert(Movie).values(
            archive_channel_id=channel_id,
            poster_message_id=parsed_group.poster_message_id,
            display_title=parsed_group.display_title,
            normalized_title=parsed_group.normalized_title,
            year=parsed_group.year,
            parser_style=parsed_group.parser_style.value,
            status="pending",
            raw_poster_caption=parsed_group.raw_poster_caption,
            parser_confidence=parsed_group.poster_confidence,
        )
        statement = statement.on_conflict_do_update(
            constraint="uq_movies_archive_poster",
            set_={
                "display_title": statement.excluded.display_title,
                "normalized_title": statement.excluded.normalized_title,
                "year": statement.excluded.year,
                "parser_style": statement.excluded.parser_style,
                "raw_poster_caption": statement.excluded.raw_poster_caption,
                "parser_confidence": statement.excluded.parser_confidence,
                "updated_at": func.now(),
            },
        ).returning(
            Movie.id,
            Movie.display_title,
            Movie.owner_notification_message_id,
            Movie.owner_notification_quality_count,
        )

        row = (await session.execute(statement)).one()
        count = await self._quality_count(session, row.id)

        return ArchiveIndexResult(
            action=IndexAction.POSTER_UPSERTED,
            movie_id=row.id,
            display_title=row.display_title,
            quality_count=count,
            owner_notification_message_id=row.owner_notification_message_id,
            owner_notification_quality_count=row.owner_notification_quality_count,
        )

    async def _upsert_quality(
        self,
        *,
        session: AsyncSession,
        channel_id: int,
        message: ArchiveMessage,
    ) -> ArchiveIndexResult:
        movie = await session.scalar(
            select(Movie)
            .where(
                Movie.archive_channel_id == channel_id,
                Movie.poster_message_id < message.message_id,
            )
            .order_by(Movie.poster_message_id.desc())
            .limit(1)
            .with_for_update()
        )
        if movie is None:
            return ArchiveIndexResult(IndexAction.IGNORED)

        poster = ArchiveMessage(
            message_id=movie.poster_message_id,
            media_kind=MediaKind.PHOTO,
            caption=movie.raw_poster_caption,
        )
        parsed_groups = self._parser.parse([poster, message])
        if not parsed_groups:
            return ArchiveIndexResult(IndexAction.IGNORED)

        parsed_group = parsed_groups[0]
        if parsed_group.status is GroupStatus.AMBIGUOUS:
            return await self._result_for_movie(
                session=session,
                movie=movie,
                action=IndexAction.AMBIGUOUS,
                diagnostic="quality_candidate_ambiguous",
            )
        if not parsed_group.qualities:
            return await self._result_for_movie(
                session=session,
                movie=movie,
                action=IndexAction.IGNORED,
            )

        quality = parsed_group.qualities[0]
        base_insert = insert(MovieQuality).values(
            movie_id=movie.id,
            archive_channel_id=channel_id,
            archive_message_id=quality.message_id,
            quality=quality.quality,
            raw_caption=quality.raw_caption,
            extracted_title=quality.raw_title,
            normalized_title=quality.normalized_title,
            extracted_year=quality.year,
            parser_confidence=quality.confidence,
        )
        upsert = base_insert.on_conflict_do_update(
            constraint="uq_movie_qualities_movie_quality",
            set_={
                "archive_channel_id": base_insert.excluded.archive_channel_id,
                "archive_message_id": base_insert.excluded.archive_message_id,
                "raw_caption": base_insert.excluded.raw_caption,
                "extracted_title": base_insert.excluded.extracted_title,
                "normalized_title": base_insert.excluded.normalized_title,
                "extracted_year": base_insert.excluded.extracted_year,
                "parser_confidence": base_insert.excluded.parser_confidence,
            },
            where=(
                base_insert.excluded.archive_message_id
                > MovieQuality.archive_message_id
            ),
        ).returning(MovieQuality.id)

        changed = (await session.execute(upsert)).scalar_one_or_none() is not None
        status = await self._refresh_movie_status(session, movie)

        return await self._result_for_movie(
            session=session,
            movie=movie,
            action=(
                IndexAction.AMBIGUOUS
                if status == "ambiguous"
                else (
                    IndexAction.QUALITY_UPSERTED
                    if changed
                    else IndexAction.DUPLICATE
                )
            ),
            diagnostic=(
                "quality_saved_but_movie_has_invalid_archive_metadata"
                if status == "ambiguous"
                else None
            ),
        )

    async def _result_for_movie(
        self,
        *,
        session: AsyncSession,
        movie: Movie,
        action: IndexAction,
        diagnostic: str | None = None,
    ) -> ArchiveIndexResult:
        count = await self._quality_count(session, movie.id)
        return ArchiveIndexResult(
            action=action,
            movie_id=movie.id,
            display_title=movie.display_title,
            quality_count=count,
            owner_notification_message_id=movie.owner_notification_message_id,
            owner_notification_quality_count=movie.owner_notification_quality_count,
            diagnostic=diagnostic,
        )

    @staticmethod
    async def _quality_count(session: AsyncSession, movie_id: int) -> int:
        value = await session.scalar(
            select(func.count(MovieQuality.id)).where(MovieQuality.movie_id == movie_id)
        )
        return int(value or 0)

    @staticmethod
    async def _refresh_movie_status(
        session: AsyncSession,
        movie: Movie,
    ) -> str:
        # Database sessions intentionally disable autoflush. Persist pending
        # poster/quality edits before the aggregate safety check so it cannot
        # make a state transition from stale parser confidence values.
        await session.flush()
        total, invalid = (
            await session.execute(
                select(
                    func.count(MovieQuality.id),
                    func.count(MovieQuality.id).filter(
                        MovieQuality.parser_confidence <= 0
                    ),
                ).where(MovieQuality.movie_id == movie.id)
            )
        ).one()

        if movie.parser_confidence <= 0 or int(invalid or 0) > 0:
            movie.status = "ambiguous"
        elif int(total or 0) > 0:
            movie.status = "indexed"
        else:
            movie.status = "orphan"
        return movie.status
