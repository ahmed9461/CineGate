from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from cinegate.db.archive_models import ArchiveMessageSnapshot
from cinegate.db.models import Movie, MovieQuality
from cinegate.db.session import Database
from cinegate.domain.archive import (
    ArchiveMessage,
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

    async def snapshot_versions(self, channel_id: int, message_ids: list[int]) -> dict[int, int]:
        """Capture optimistic history-read tokens before contacting Telegram."""
        async with self._database.session() as session:
            rows = await session.execute(
                select(ArchiveMessageSnapshot.message_id, ArchiveMessageSnapshot.version).where(
                    ArchiveMessageSnapshot.archive_channel_id == channel_id,
                    ArchiveMessageSnapshot.message_id.in_(message_ids),
                )
            )
            return {**dict.fromkeys(message_ids, 0), **dict(rows.all())}

    async def reconcile_edit(
        self,
        *,
        channel_id: int,
        message: ArchiveMessage,
        expected_snapshot_version: int | None = None,
    ) -> ArchiveIndexResult:
        async with self._database.session() as session, session.begin():
            configured_channel_id = await SettingsRepository(session).get_int("archive_channel_id")
            if configured_channel_id is None or configured_channel_id != channel_id:
                return ArchiveIndexResult(IndexAction.IGNORED)

            if not await self._record_snapshot(
                session,
                channel_id,
                message,
                reconcile=True,
                expected_version=expected_snapshot_version,
            ):
                return await self._duplicate_result(session, channel_id, message.message_id)

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
                    return await self._reconcile_boundary(session, channel_id, message.message_id)
                return await self._upsert_poster(
                    session=session,
                    channel_id=channel_id,
                    parsed_group=parsed[0],
                )

            if message.media_kind in {MediaKind.VIDEO, MediaKind.DOCUMENT}:
                if extract_quality(message.caption) is None:
                    return await self._reconcile_boundary(session, channel_id, message.message_id)
                return await self._upsert_quality(
                    session=session,
                    channel_id=channel_id,
                    message=message,
                )

            return await self._reconcile_boundary(session, channel_id, message.message_id)

    async def ingest(
        self,
        *,
        channel_id: int,
        message: ArchiveMessage,
    ) -> ArchiveIndexResult:
        async with self._database.session() as session, session.begin():
            configured_channel_id = await SettingsRepository(session).get_int("archive_channel_id")
            if configured_channel_id is None or configured_channel_id != channel_id:
                return ArchiveIndexResult(IndexAction.IGNORED)

            if not await self._record_snapshot(session, channel_id, message, reconcile=False):
                return await self._duplicate_result(session, channel_id, message.message_id)

            if message.media_kind is MediaKind.PHOTO:
                parsed = self._parser.parse([message])
                if not parsed:
                    return await self._reconcile_boundary(session, channel_id, message.message_id)
                return await self._upsert_poster(
                    session=session,
                    channel_id=channel_id,
                    parsed_group=parsed[0],
                )

            if message.media_kind in {MediaKind.VIDEO, MediaKind.DOCUMENT}:
                if extract_quality(message.caption) is None:
                    return await self._reconcile_boundary(session, channel_id, message.message_id)
                return await self._upsert_quality(
                    session=session,
                    channel_id=channel_id,
                    message=message,
                )

            return await self._reconcile_boundary(session, channel_id, message.message_id)

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

        await self._revalidate_attached_qualities(session, movie)
        status = await self._refresh_movie_status(session, movie)
        return await self._result_for_movie(
            session=session,
            movie=movie,
            action=(
                IndexAction.AMBIGUOUS if status == "ambiguous" else IndexAction.POSTER_UPSERTED
            ),
            diagnostic=(
                "edited_poster_valid_but_quality_remains_invalid" if status == "ambiguous" else None
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

        group = await self._parse_movie_group(session, movie, through=message.message_id)
        parsed = (
            next(
                (item for item in group.qualities if item.message_id == message.message_id),
                None,
            )
            if group is not None
            else None
        )
        if parsed is None:
            return await self._invalidate_quality_edit(
                session=session,
                movie=movie,
                quality_row=quality_row,
                message=message,
                diagnostic="edited_quality_ambiguous",
            )

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
        await self._revalidate_attached_qualities(session, movie)
        status = await self._refresh_movie_status(session, movie)

        return await self._result_for_movie(
            session=session,
            movie=movie,
            action=(
                IndexAction.AMBIGUOUS if status == "ambiguous" else IndexAction.QUALITY_UPSERTED
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
        statement = statement.on_conflict_do_nothing(
            constraint="uq_movies_archive_poster",
        ).returning(
            Movie.id,
            Movie.display_title,
            Movie.owner_notification_message_id,
            Movie.owner_notification_quality_count,
        )

        row = (await session.execute(statement)).one_or_none()
        if row is None:
            return await self._duplicate_result(session, channel_id, parsed_group.poster_message_id)
        if previous is not None:
            await self._revalidate_attached_qualities(session, previous)
            await self._refresh_movie_status(session, previous)
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

        parsed_group = await self._parse_movie_group(session, movie, through=message.message_id)
        if parsed_group is None:
            return ArchiveIndexResult(IndexAction.IGNORED)
        quality = next(
            (item for item in parsed_group.qualities if item.message_id == message.message_id),
            None,
        )
        if quality is None:
            ambiguous = any(
                diagnostic.startswith(f"ambiguous_quality:{message.message_id}:")
                for diagnostic in parsed_group.diagnostics
            )
            return await self._result_for_movie(
                session=session,
                movie=movie,
                action=IndexAction.AMBIGUOUS if ambiguous else IndexAction.IGNORED,
                diagnostic="quality_candidate_ambiguous" if ambiguous else None,
            )

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
            where=(base_insert.excluded.archive_message_id > MovieQuality.archive_message_id),
        ).returning(MovieQuality.id)

        changed = (await session.execute(upsert)).scalar_one_or_none() is not None
        await self._revalidate_attached_qualities(session, movie)
        status = await self._refresh_movie_status(session, movie)

        return await self._result_for_movie(
            session=session,
            movie=movie,
            action=(
                IndexAction.AMBIGUOUS
                if status == "ambiguous"
                else (IndexAction.QUALITY_UPSERTED if changed else IndexAction.DUPLICATE)
            ),
            diagnostic=(
                "quality_saved_but_movie_has_invalid_archive_metadata"
                if status == "ambiguous"
                else None
            ),
        )

    async def _record_snapshot(
        self,
        session: AsyncSession,
        channel_id: int,
        message: ArchiveMessage,
        *,
        reconcile: bool,
        expected_version: int | None = None,
    ) -> bool:
        # All index mutations use this lock before movie -> quality row locks.
        # It protects durable sequence evidence from concurrent edit/replay races.
        await session.execute(
            select(
                func.pg_advisory_xact_lock(
                    func.hashtextextended(f"cinegate:archive:{channel_id}", 0)
                )
            )
        )
        snapshot = await session.get(ArchiveMessageSnapshot, (channel_id, message.message_id))
        if expected_version is not None and expected_version != (
            snapshot.version if snapshot is not None else 0
        ):
            # A live event committed after the history read began. Its index
            # result is authoritative; the stale fetched message cannot undo it.
            return False
        if snapshot is None:
            session.add(
                ArchiveMessageSnapshot(
                    archive_channel_id=channel_id,
                    message_id=message.message_id,
                    media_kind=message.media_kind.value,
                    caption=message.caption,
                    edited_at=message.edited_at,
                )
            )
        else:
            if not reconcile:
                return False
            if snapshot.edited_at is not None:
                if message.edited_at is None or message.edited_at < snapshot.edited_at:
                    return False
                if message.edited_at == snapshot.edited_at and expected_version is None:
                    if (message.media_kind.value, message.caption) != (
                        snapshot.media_kind,
                        snapshot.caption,
                    ):
                        # Telegram only gives second precision. Preserve prior
                        # evidence, but hide an uncertain association and fence
                        # any in-flight history read until a fresh read resolves it.
                        snapshot.version += 1
                        snapshot.conflicted = True
                        await session.flush()
                        await self._invalidate_snapshot_conflict(
                            session, channel_id, message.message_id
                        )
                    return False
            snapshot.conflicted = False
            snapshot.version += 1
            snapshot.media_kind = message.media_kind.value
            snapshot.caption = message.caption
            snapshot.edited_at = message.edited_at
        await session.flush()
        return True

    async def _invalidate_snapshot_conflict(
        self, session: AsyncSession, channel_id: int, message_id: int
    ) -> None:
        movie = await session.scalar(
            select(Movie)
            .where(
                Movie.archive_channel_id == channel_id,
                Movie.poster_message_id == message_id,
            )
            .with_for_update()
        )
        if movie is not None:
            movie.parser_confidence = 0
            movie.status = "ambiguous"
            return
        movie = await session.scalar(
            select(Movie)
            .join(MovieQuality)
            .where(
                MovieQuality.archive_channel_id == channel_id,
                MovieQuality.archive_message_id == message_id,
            )
            .with_for_update(of=Movie)
        )
        if movie is not None:
            quality = await session.scalar(
                select(MovieQuality)
                .where(
                    MovieQuality.movie_id == movie.id,
                    MovieQuality.archive_channel_id == channel_id,
                    MovieQuality.archive_message_id == message_id,
                )
                .with_for_update()
            )
            quality.parser_confidence = 0
            movie.status = "ambiguous"
        else:
            await self._reconcile_boundary(session, channel_id, message_id)

    async def _duplicate_result(
        self, session: AsyncSession, channel_id: int, message_id: int
    ) -> ArchiveIndexResult:
        movie = await session.scalar(
            select(Movie).where(
                Movie.archive_channel_id == channel_id,
                Movie.poster_message_id == message_id,
            )
        )
        if movie is None:
            movie = await session.scalar(
                select(Movie)
                .join(MovieQuality)
                .where(
                    MovieQuality.archive_channel_id == channel_id,
                    MovieQuality.archive_message_id == message_id,
                )
            )
        if movie is None:
            return ArchiveIndexResult(IndexAction.IGNORED)
        return await self._result_for_movie(
            session=session,
            movie=movie,
            action=IndexAction.AMBIGUOUS if movie.status == "ambiguous" else IndexAction.DUPLICATE,
        )

    async def _parse_movie_group(
        self, session: AsyncSession, movie: Movie, *, through: int | None = None
    ) -> ParsedMovieGroup | None:
        if movie.parser_confidence <= 0:
            return None
        next_poster = (
            select(func.min(Movie.poster_message_id))
            .where(
                Movie.archive_channel_id == movie.archive_channel_id,
                Movie.poster_message_id > movie.poster_message_id,
            )
            .scalar_subquery()
        )
        first_conflict = (
            select(func.min(ArchiveMessageSnapshot.message_id))
            .where(
                ArchiveMessageSnapshot.archive_channel_id == movie.archive_channel_id,
                ArchiveMessageSnapshot.message_id >= movie.poster_message_id,
                ArchiveMessageSnapshot.message_id < func.coalesce(next_poster, 9223372036854775807),
                ArchiveMessageSnapshot.conflicted.is_(True),
            )
            .scalar_subquery()
        )
        statement = (
            select(ArchiveMessageSnapshot)
            .where(
                ArchiveMessageSnapshot.archive_channel_id == movie.archive_channel_id,
                ArchiveMessageSnapshot.message_id >= movie.poster_message_id,
                ArchiveMessageSnapshot.message_id
                < func.least(
                    func.coalesce(next_poster, 9223372036854775807),
                    func.coalesce(first_conflict, 9223372036854775807),
                ),
            )
            .order_by(ArchiveMessageSnapshot.message_id)
        )
        if through is not None:
            statement = statement.where(ArchiveMessageSnapshot.message_id <= through)

        def parse_stream(sync_session):
            # Server-side batches keep memory bounded even for long noisy ranges.
            rows = sync_session.scalars(statement.execution_options(yield_per=100))
            try:
                messages = (
                    ArchiveMessage(
                        message_id=row.message_id,
                        media_kind=MediaKind.OTHER if row.conflicted else MediaKind(row.media_kind),
                        caption=row.caption,
                        edited_at=row.edited_at,
                    )
                    for row in rows
                )
                return next(self._parser.iter_groups(messages, diagnostic_limit=32), None)
            finally:
                rows.close()

        group = await session.run_sync(parse_stream)
        if group is not None and group.poster_message_id == movie.poster_message_id:
            return group
        return None

    async def _revalidate_attached_qualities(self, session: AsyncSession, movie: Movie) -> None:
        await session.flush()
        group = await self._parse_movie_group(session, movie)
        accepted = {item.message_id: item for item in group.qualities} if group else {}
        qualities = (
            await session.scalars(
                select(MovieQuality).where(MovieQuality.movie_id == movie.id).with_for_update()
            )
        ).all()
        for row in qualities:
            parsed = accepted.get(row.archive_message_id)
            if parsed is None or parsed.quality != row.quality:
                row.parser_confidence = 0
            else:
                row.parser_confidence = parsed.confidence
                row.extracted_title = parsed.raw_title
                row.normalized_title = parsed.normalized_title
                row.extracted_year = parsed.year

    async def _reconcile_boundary(
        self, session: AsyncSession, channel_id: int, message_id: int
    ) -> ArchiveIndexResult:
        movie = await session.scalar(
            select(Movie)
            .where(
                Movie.archive_channel_id == channel_id,
                Movie.poster_message_id < message_id,
            )
            .order_by(Movie.poster_message_id.desc())
            .limit(1)
            .with_for_update()
        )
        if movie is not None:
            await self._revalidate_attached_qualities(session, movie)
            await self._refresh_movie_status(session, movie)
        return ArchiveIndexResult(IndexAction.IGNORED)

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
                    func.count(MovieQuality.id).filter(MovieQuality.parser_confidence <= 0),
                ).where(MovieQuality.movie_id == movie.id)
            )
        ).one()

        next_poster = (
            select(func.min(Movie.poster_message_id))
            .where(
                Movie.archive_channel_id == movie.archive_channel_id,
                Movie.poster_message_id > movie.poster_message_id,
            )
            .scalar_subquery()
        )
        conflict = await session.scalar(
            select(ArchiveMessageSnapshot.message_id)
            .where(
                ArchiveMessageSnapshot.archive_channel_id == movie.archive_channel_id,
                ArchiveMessageSnapshot.message_id >= movie.poster_message_id,
                ArchiveMessageSnapshot.message_id < func.coalesce(next_poster, 9223372036854775807),
                ArchiveMessageSnapshot.conflicted.is_(True),
            )
            .limit(1)
        )
        if movie.parser_confidence <= 0 or int(invalid or 0) > 0 or conflict is not None:
            movie.status = "ambiguous"
        elif int(total or 0) > 0:
            movie.status = "indexed"
        else:
            movie.status = "orphan"
        return movie.status
