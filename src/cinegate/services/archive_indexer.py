from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from cinegate.db.models import Movie, MovieQuality
from cinegate.db.session import Database
from cinegate.domain.archive import ArchiveMessage, GroupStatus, MediaKind
from cinegate.domain.indexing import ArchiveIndexResult, IndexAction
from cinegate.repositories.settings import SettingsRepository
from cinegate.services.archive_parser import ArchiveParser
from cinegate.services.text import extract_quality


class ArchiveIndexService:
    """Persist one Archive Channel message safely and idempotently."""

    def __init__(self, database: Database, *, parser: ArchiveParser | None = None) -> None:
        self._database = database
        self._parser = parser or ArchiveParser()

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

    async def _upsert_poster(
        self,
        *,
        session: AsyncSession,
        channel_id: int,
        parsed_group,
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
        )

        row = (await session.execute(statement)).one()
        count = await self._quality_count(session, row.id)

        return ArchiveIndexResult(
            action=IndexAction.POSTER_UPSERTED,
            movie_id=row.id,
            display_title=row.display_title,
            quality_count=count,
            owner_notification_message_id=row.owner_notification_message_id,
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
            return ArchiveIndexResult(
                action=IndexAction.AMBIGUOUS,
                movie_id=movie.id,
                display_title=movie.display_title,
                owner_notification_message_id=movie.owner_notification_message_id,
                diagnostic="quality_candidate_ambiguous",
            )
        if not parsed_group.qualities:
            return ArchiveIndexResult(
                action=IndexAction.IGNORED,
                movie_id=movie.id,
                display_title=movie.display_title,
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
        movie.status = "indexed"
        count = await self._quality_count(session, movie.id)

        return ArchiveIndexResult(
            action=IndexAction.QUALITY_UPSERTED if changed else IndexAction.DUPLICATE,
            movie_id=movie.id,
            display_title=movie.display_title,
            quality_count=count,
            owner_notification_message_id=movie.owner_notification_message_id,
        )

    @staticmethod
    async def _quality_count(session: AsyncSession, movie_id: int) -> int:
        value = await session.scalar(
            select(func.count(MovieQuality.id)).where(MovieQuality.movie_id == movie_id)
        )
        return int(value or 0)
