from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from cinegate.db.models import Movie, MovieQuality
from cinegate.db.session import Database
from cinegate.importer.adapter import is_importable_message
from cinegate.importer.errors import HistoricalImportError
from cinegate.importer.gateway import HistoricalTelegramGateway
from cinegate.repositories.settings import SettingsRepository


@dataclass(frozen=True, slots=True)
class MissingArchiveReference:
    kind: str
    row_id: int
    archive_message_id: int


@dataclass(frozen=True, slots=True)
class ArchiveIntegrityReport:
    checked_posters: int
    checked_qualities: int
    missing_posters: int
    missing_qualities: int
    missing_examples: tuple[MissingArchiveReference, ...]

    @property
    def ok(self) -> bool:
        return self.missing_posters == 0 and self.missing_qualities == 0


class ArchiveIntegrityAuditService:
    """Read-only audit of indexed Telegram Archive references."""

    def __init__(
        self,
        *,
        database: Database,
        gateway: HistoricalTelegramGateway,
        batch_size: int = 100,
        example_limit: int = 20,
    ) -> None:
        if not 1 <= batch_size <= 500:
            raise ValueError("batch_size must be between 1 and 500")
        if not 1 <= example_limit <= 100:
            raise ValueError("example_limit must be between 1 and 100")

        self._database = database
        self._gateway = gateway
        self._batch_size = batch_size
        self._example_limit = example_limit

    async def verify(self) -> ArchiveIntegrityReport:
        archive_channel_id = await self._archive_channel_id()
        archive = await self._gateway.resolve_channel(archive_channel_id)

        poster_checked, poster_missing, poster_examples = (
            await self._audit_posters(
                archive=archive,
                archive_channel_id=archive_channel_id,
            )
        )
        quality_checked, quality_missing, quality_examples = (
            await self._audit_qualities(
                archive=archive,
                archive_channel_id=archive_channel_id,
            )
        )

        examples = tuple(
            (poster_examples + quality_examples)[: self._example_limit]
        )
        return ArchiveIntegrityReport(
            checked_posters=poster_checked,
            checked_qualities=quality_checked,
            missing_posters=poster_missing,
            missing_qualities=quality_missing,
            missing_examples=examples,
        )

    async def _archive_channel_id(self) -> int:
        async with self._database.session() as session:
            value = await SettingsRepository(session).get_int(
                "archive_channel_id"
            )
        if value is None:
            raise HistoricalImportError(
                "archive_channel_id is not configured"
            )
        return value

    async def _audit_posters(
        self,
        *,
        archive,
        archive_channel_id: int,
    ) -> tuple[int, int, list[MissingArchiveReference]]:
        checked = 0
        missing = 0
        examples: list[MissingArchiveReference] = []
        after_id = 0

        while True:
            async with self._database.session() as session:
                rows = (
                    await session.execute(
                        select(
                            Movie.id,
                            Movie.poster_message_id,
                        )
                        .where(
                            Movie.archive_channel_id == archive_channel_id,
                            Movie.status == "indexed",
                            Movie.id > after_id,
                        )
                        .order_by(Movie.id)
                        .limit(self._batch_size)
                    )
                ).all()

            if not rows:
                break

            messages = await self._gateway.get_messages_by_ids(
                archive,
                [row.poster_message_id for row in rows],
            )
            _require_same_length(rows, messages)

            for row, message in zip(rows, messages, strict=True):
                checked += 1
                if not is_importable_message(message):
                    missing += 1
                    if len(examples) < self._example_limit:
                        examples.append(
                            MissingArchiveReference(
                                kind="poster",
                                row_id=row.id,
                                archive_message_id=row.poster_message_id,
                            )
                        )

            after_id = rows[-1].id

        return checked, missing, examples

    async def _audit_qualities(
        self,
        *,
        archive,
        archive_channel_id: int,
    ) -> tuple[int, int, list[MissingArchiveReference]]:
        checked = 0
        missing = 0
        examples: list[MissingArchiveReference] = []
        after_id = 0

        while True:
            async with self._database.session() as session:
                rows = (
                    await session.execute(
                        select(
                            MovieQuality.id,
                            MovieQuality.archive_message_id,
                        )
                        .join(Movie, Movie.id == MovieQuality.movie_id)
                        .where(
                            Movie.archive_channel_id == archive_channel_id,
                            Movie.status == "indexed",
                            MovieQuality.id > after_id,
                        )
                        .order_by(MovieQuality.id)
                        .limit(self._batch_size)
                    )
                ).all()

            if not rows:
                break

            messages = await self._gateway.get_messages_by_ids(
                archive,
                [row.archive_message_id for row in rows],
            )
            _require_same_length(rows, messages)

            for row, message in zip(rows, messages, strict=True):
                checked += 1
                if not is_importable_message(message):
                    missing += 1
                    if len(examples) < self._example_limit:
                        examples.append(
                            MissingArchiveReference(
                                kind="quality",
                                row_id=row.id,
                                archive_message_id=row.archive_message_id,
                            )
                        )

            after_id = rows[-1].id

        return checked, missing, examples


def _require_same_length(rows, messages) -> None:
    if len(rows) != len(messages):
        raise HistoricalImportError(
            "Archive audit returned an unexpected Telegram result length"
        )
