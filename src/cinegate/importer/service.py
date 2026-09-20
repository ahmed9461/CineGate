from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from cinegate.db.session import Database
from cinegate.importer.adapter import (
    forwarded_source_message_id,
    is_importable_message,
    telethon_message_to_archive,
)
from cinegate.importer.errors import (
    HistoricalImportError,
    ImportChannelAccessError,
    ImportFloodWaitTooLong,
    SourceForwardingRestricted,
)
from cinegate.importer.gateway import HistoricalTelegramGateway
from cinegate.importer.lock import historical_import_lock
from cinegate.repositories.import_jobs import (
    ArchiveImportRepository,
    ImportJobSnapshot,
)
from cinegate.repositories.settings import SettingsRepository
from cinegate.services.archive_indexer import ArchiveIndexService

ProgressCallback = Callable[[ImportJobSnapshot], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class HistoricalImportResult:
    job: ImportJobSnapshot


class HistoricalImportService:
    """Resumable one-time source→Archive transfer and reindex."""

    def __init__(
        self,
        *,
        database: Database,
        gateway: HistoricalTelegramGateway,
        batch_size: int = 25,
        reindex_batch_size: int = 100,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        if not 1 <= batch_size <= 100:
            raise ValueError("batch_size must be between 1 and 100")
        if not 1 <= reindex_batch_size <= 500:
            raise ValueError("reindex_batch_size must be between 1 and 500")

        self._database = database
        self._gateway = gateway
        self._batch_size = batch_size
        self._reindex_batch_size = reindex_batch_size
        self._progress_callback = progress_callback
        self._indexer = ArchiveIndexService(database)

    async def run(
        self,
        *,
        source_channel_id: int,
        archive_channel_id: int,
    ) -> HistoricalImportResult:
        job = await self.transfer(
            source_channel_id=source_channel_id,
            archive_channel_id=archive_channel_id,
        )
        job = await self.reindex(
            job_id=job.id,
            full=False,
        )
        return HistoricalImportResult(job=job)

    async def transfer(
        self,
        *,
        source_channel_id: int,
        archive_channel_id: int,
    ) -> ImportJobSnapshot:
        async with historical_import_lock(
            self._database,
            source_channel_id=source_channel_id,
            archive_channel_id=archive_channel_id,
        ):
            source, archive = await self._gateway.resolve_channels(
                source_channel_id=source_channel_id,
                archive_channel_id=archive_channel_id,
            )
            job = await self._get_or_create_job(
                source_channel_id=source_channel_id,
                archive_channel_id=archive_channel_id,
            )

            if job.status == "completed":
                return job

            job = await self._initialize_snapshot_if_needed(
                job=job,
                source=source,
                archive=archive,
            )
            await self._reconcile_archive_tail(
                job=job,
                archive=archive,
            )
            job = await self._mark_running(job.id)
            await self._report(job)

            try:
                job = await self._transfer_messages(
                    job=job,
                    source=source,
                    archive=archive,
                )
            except (SourceForwardingRestricted, ImportFloodWaitTooLong) as exc:
                job = await self._mark_paused(job.id, str(exc))
                await self._report(job)
                raise
            except ImportChannelAccessError as exc:
                job = await self._mark_failed(job.id, str(exc))
                await self._report(job)
                raise
            except HistoricalImportError as exc:
                job = await self._mark_paused(job.id, str(exc))
                await self._report(job)
                raise

            job = await self._mark_transferred(job.id)
            await self._report(job)
            return job

    async def reindex(
        self,
        *,
        job_id,
        full: bool,
    ) -> ImportJobSnapshot:
        job = await self._get_job(job_id)
        if job is None:
            raise HistoricalImportError("historical import job not found")
        if job.status not in {"transferred", "reindexing", "completed"}:
            raise HistoricalImportError(
                f"cannot reindex import job while status={job.status}"
            )

        async with historical_import_lock(
            self._database,
            source_channel_id=job.source_channel_id,
            archive_channel_id=job.archive_channel_id,
        ):
            archive = await self._gateway.resolve_channel(job.archive_channel_id)
            await self._ensure_archive_setting(job.archive_channel_id)

            if job.status != "completed":
                job = await self._mark_reindexing(job.id)
                await self._report(job)

            after_source_id = 0 if full else job.last_reindexed_source_message_id

            while True:
                mappings = await self._list_mappings(
                    job_id=job.id,
                    after_source_message_id=after_source_id,
                )
                if not mappings:
                    break

                archive_ids = [mapping.archive_message_id for mapping in mappings]
                messages = await self._gateway.get_messages_by_ids(
                    archive,
                    archive_ids,
                )
                if len(messages) != len(mappings):
                    raise HistoricalImportError(
                        "archive message lookup returned an unexpected result length"
                    )

                for mapping, message in zip(mappings, messages, strict=True):
                    if message is None:
                        await self._mark_reindexed(
                            job_id=job.id,
                            source_message_id=mapping.source_message_id,
                            missing=True,
                        )
                    else:
                        await self._indexer.ingest(
                            channel_id=job.archive_channel_id,
                            message=telethon_message_to_archive(message),
                        )
                        await self._mark_reindexed(
                            job_id=job.id,
                            source_message_id=mapping.source_message_id,
                            missing=False,
                        )

                    after_source_id = mapping.source_message_id

                job = await self._get_job_required(job.id)
                await self._report(job)

            if job.status != "completed":
                job = await self._mark_completed(job.id)
                await self._report(job)

            return job

    async def _initialize_snapshot_if_needed(
        self,
        *,
        job: ImportJobSnapshot,
        source: Any,
        archive: Any,
    ) -> ImportJobSnapshot:
        if job.source_high_watermark_id is not None:
            return job

        source_high = await self._gateway.latest_message_id(source)
        archive_baseline = await self._gateway.latest_message_id(archive)
        total = await self._gateway.total_message_estimate(source)

        async with self._database.session() as session, session.begin():
            return await ArchiveImportRepository(session).initialize_snapshot(
                job_id=job.id,
                source_high_watermark_id=source_high,
                archive_baseline_message_id=archive_baseline,
                source_total_estimate=total,
            )

    async def _reconcile_archive_tail(
        self,
        *,
        job: ImportJobSnapshot,
        archive: Any,
    ) -> None:
        if job.source_high_watermark_id is None:
            raise HistoricalImportError("import snapshot is not initialized")

        async with self._database.session() as session:
            repository = ArchiveImportRepository(session)
            last_mapped_archive_id = await repository.max_mapped_archive_message_id(
                job.id
            )

        after_archive_id = (
            last_mapped_archive_id
            if last_mapped_archive_id is not None
            else int(job.archive_baseline_message_id or 0)
        )

        pending: list[tuple[int, int]] = []
        async for message in self._gateway.iter_archive_messages_after(
            archive,
            after_message_id=after_archive_id,
        ):
            source_message_id = forwarded_source_message_id(
                message,
                expected_source_channel_id=job.source_channel_id,
            )
            if source_message_id is None:
                continue
            if source_message_id > job.source_high_watermark_id:
                continue

            pending.append((source_message_id, int(message.id)))
            if len(pending) >= 100:
                await self._record_reconciled(job.id, tuple(pending))
                pending.clear()

        if pending:
            await self._record_reconciled(job.id, tuple(pending))

    async def _transfer_messages(
        self,
        *,
        job: ImportJobSnapshot,
        source: Any,
        archive: Any,
    ) -> ImportJobSnapshot:
        if job.source_high_watermark_id is None:
            raise HistoricalImportError("import snapshot is not initialized")

        async for batch in self._source_batches(
            source,
            after_message_id=job.last_copied_source_message_id,
            high_watermark_id=job.source_high_watermark_id,
        ):
            source_ids = tuple(int(message.id) for message in batch)
            _require_strictly_increasing(source_ids, "source message IDs")

            importable = tuple(
                message for message in batch if is_importable_message(message)
            )
            importable_ids = tuple(int(message.id) for message in importable)
            mapped = await self._mapped_source_ids(job.id, importable_ids)

            to_forward = tuple(
                message
                for message in importable
                if int(message.id) not in mapped
            )

            forwarded_mappings: tuple[tuple[int, int], ...] = ()
            if to_forward:
                forwarded = await self._gateway.forward_batch(
                    source=source,
                    archive=archive,
                    messages=to_forward,
                )
                if len(forwarded) != len(to_forward) or any(
                    message is None for message in forwarded
                ):
                    raise HistoricalImportError(
                        "Telegram returned a partial forwarding batch; "
                        "restart to reconcile before retry"
                    )

                archive_ids = tuple(int(message.id) for message in forwarded)
                _require_strictly_increasing(
                    archive_ids,
                    "archive message IDs",
                )
                forwarded_mappings = tuple(
                    (int(source_message.id), int(archive_message.id))
                    for source_message, archive_message in zip(
                        to_forward,
                        forwarded,
                        strict=True,
                    )
                )

            skipped_count = len(batch) - len(importable)
            await self._record_transfer_batch(
                job_id=job.id,
                processed_through_source_id=source_ids[-1],
                processed_count=len(batch),
                skipped_count=skipped_count,
                forwarded_mappings=forwarded_mappings,
            )
            job = await self._get_job_required(job.id)
            await self._report(job)

        return job

    async def _source_batches(
        self,
        source: Any,
        *,
        after_message_id: int,
        high_watermark_id: int,
    ) -> AsyncIterator[tuple[Any, ...]]:
        batch: list[Any] = []
        async for message in self._gateway.iter_source_messages(
            source,
            after_message_id=after_message_id,
            high_watermark_id=high_watermark_id,
        ):
            batch.append(message)
            if len(batch) >= self._batch_size:
                yield tuple(batch)
                batch.clear()

        if batch:
            yield tuple(batch)

    async def _get_or_create_job(
        self,
        *,
        source_channel_id: int,
        archive_channel_id: int,
    ) -> ImportJobSnapshot:
        async with self._database.session() as session, session.begin():
            return await ArchiveImportRepository(session).get_or_create_job(
                source_channel_id=source_channel_id,
                archive_channel_id=archive_channel_id,
            )

    async def _get_job(self, job_id) -> ImportJobSnapshot | None:
        async with self._database.session() as session:
            return await ArchiveImportRepository(session).get_job(job_id)

    async def _get_job_required(self, job_id) -> ImportJobSnapshot:
        job = await self._get_job(job_id)
        if job is None:
            raise HistoricalImportError("historical import job not found")
        return job

    async def _mark_running(self, job_id) -> ImportJobSnapshot:
        async with self._database.session() as session, session.begin():
            return await ArchiveImportRepository(session).mark_running(job_id)

    async def _mark_paused(self, job_id, error: str) -> ImportJobSnapshot:
        async with self._database.session() as session, session.begin():
            return await ArchiveImportRepository(session).mark_paused(job_id, error)

    async def _mark_failed(self, job_id, error: str) -> ImportJobSnapshot:
        async with self._database.session() as session, session.begin():
            return await ArchiveImportRepository(session).mark_failed(job_id, error)

    async def _mark_transferred(self, job_id) -> ImportJobSnapshot:
        async with self._database.session() as session, session.begin():
            return await ArchiveImportRepository(session).mark_transferred(job_id)

    async def _mark_reindexing(self, job_id) -> ImportJobSnapshot:
        async with self._database.session() as session, session.begin():
            return await ArchiveImportRepository(session).mark_reindexing(job_id)

    async def _mark_completed(self, job_id) -> ImportJobSnapshot:
        async with self._database.session() as session, session.begin():
            return await ArchiveImportRepository(session).mark_completed(job_id)

    async def _mapped_source_ids(
        self,
        job_id,
        source_message_ids: tuple[int, ...],
    ) -> set[int]:
        async with self._database.session() as session:
            return await ArchiveImportRepository(session).mapped_source_ids(
                job_id=job_id,
                source_message_ids=source_message_ids,
            )

    async def _record_reconciled(
        self,
        job_id,
        mappings: tuple[tuple[int, int], ...],
    ) -> None:
        async with self._database.session() as session, session.begin():
            await ArchiveImportRepository(session).record_reconciled_mappings(
                job_id=job_id,
                mappings=mappings,
            )

    async def _record_transfer_batch(
        self,
        *,
        job_id,
        processed_through_source_id: int,
        processed_count: int,
        skipped_count: int,
        forwarded_mappings: tuple[tuple[int, int], ...],
    ) -> None:
        async with self._database.session() as session, session.begin():
            await ArchiveImportRepository(session).record_transfer_batch(
                job_id=job_id,
                processed_through_source_id=processed_through_source_id,
                processed_count=processed_count,
                skipped_count=skipped_count,
                forwarded_mappings=forwarded_mappings,
            )

    async def _list_mappings(
        self,
        *,
        job_id,
        after_source_message_id: int,
    ):
        async with self._database.session() as session:
            return await ArchiveImportRepository(session).list_mappings_after(
                job_id=job_id,
                after_source_message_id=after_source_message_id,
                limit=self._reindex_batch_size,
            )

    async def _mark_reindexed(
        self,
        *,
        job_id,
        source_message_id: int,
        missing: bool,
    ) -> None:
        async with self._database.session() as session, session.begin():
            await ArchiveImportRepository(session).mark_reindexed(
                job_id=job_id,
                source_message_id=source_message_id,
                missing=missing,
            )

    async def _ensure_archive_setting(self, archive_channel_id: int) -> None:
        async with self._database.session() as session:
            configured = await SettingsRepository(session).get_int(
                "archive_channel_id"
            )
        if configured != archive_channel_id:
            raise HistoricalImportError(
                "archive_channel_id runtime setting does not match import job"
            )

    async def _report(self, job: ImportJobSnapshot) -> None:
        if self._progress_callback is not None:
            await self._progress_callback(job)


def _require_strictly_increasing(values: tuple[int, ...], label: str) -> None:
    if any(
        left >= right
        for left, right in zip(values, values[1:], strict=False)
    ):
        raise HistoricalImportError(f"{label} are not strictly increasing")
