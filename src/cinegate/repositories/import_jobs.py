from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from cinegate.db.models import ArchiveImportJob, ArchiveImportMessageMap

_ACTIVE_BULK_STATUSES = ("running", "paused", "transferred", "reindexing")


@dataclass(frozen=True, slots=True)
class ImportJobSnapshot:
    id: UUID
    source_channel_id: int
    archive_channel_id: int
    status: str
    source_high_watermark_id: int | None
    archive_baseline_message_id: int | None
    last_copied_source_message_id: int
    last_reindexed_source_message_id: int
    source_total_estimate: int | None
    processed_messages: int
    copied_messages: int
    reconciled_messages: int
    skipped_messages: int
    reindexed_messages: int
    missing_archive_messages: int
    owner_progress_message_id: int | None
    started_at: datetime | None
    completed_at: datetime | None
    last_error: str | None


@dataclass(frozen=True, slots=True)
class ImportMessageMapping:
    source_message_id: int
    archive_message_id: int
    reindexed_at: datetime | None


class ArchiveImportRepository:
    """Durable state/checkpoints for the one-time historical import."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_or_create_job(
        self,
        *,
        source_channel_id: int,
        archive_channel_id: int,
    ) -> ImportJobSnapshot:
        statement = insert(ArchiveImportJob).values(
            source_channel_id=source_channel_id,
            archive_channel_id=archive_channel_id,
            status="ready",
        )
        statement = statement.on_conflict_do_nothing(
            constraint="uq_archive_import_jobs_source_archive"
        )
        await self._session.execute(statement)

        job = await self._session.scalar(
            select(ArchiveImportJob)
            .where(
                ArchiveImportJob.source_channel_id == source_channel_id,
                ArchiveImportJob.archive_channel_id == archive_channel_id,
            )
            .with_for_update()
        )
        if job is None:
            raise RuntimeError("import job disappeared after upsert")
        return _snapshot(job)

    async def get_job(self, job_id: UUID, *, lock: bool = False) -> ImportJobSnapshot | None:
        statement = select(ArchiveImportJob).where(ArchiveImportJob.id == job_id)
        if lock:
            statement = statement.with_for_update()
        job = await self._session.scalar(statement)
        return _snapshot(job) if job is not None else None

    async def get_job_by_pair(
        self,
        *,
        source_channel_id: int,
        archive_channel_id: int,
    ) -> ImportJobSnapshot | None:
        job = await self._session.scalar(
            select(ArchiveImportJob).where(
                ArchiveImportJob.source_channel_id == source_channel_id,
                ArchiveImportJob.archive_channel_id == archive_channel_id,
            )
        )
        return _snapshot(job) if job is not None else None

    async def initialize_snapshot(
        self,
        *,
        job_id: UUID,
        source_high_watermark_id: int,
        archive_baseline_message_id: int,
        source_total_estimate: int | None,
    ) -> ImportJobSnapshot:
        job = await self._require_job(job_id, lock=True)

        if job.source_high_watermark_id is None:
            job.source_high_watermark_id = source_high_watermark_id
            job.archive_baseline_message_id = archive_baseline_message_id
            job.source_total_estimate = source_total_estimate

        return _snapshot(job)

    async def mark_running(self, job_id: UUID) -> ImportJobSnapshot:
        job = await self._require_job(job_id, lock=True)
        job.status = "running"
        job.started_at = job.started_at or func.now()
        job.completed_at = None
        job.last_error = None
        return _snapshot(job)

    async def mark_paused(self, job_id: UUID, error: str) -> ImportJobSnapshot:
        job = await self._require_job(job_id, lock=True)
        job.status = "paused"
        job.last_error = _bounded_error(error)
        return _snapshot(job)

    async def mark_failed(self, job_id: UUID, error: str) -> ImportJobSnapshot:
        job = await self._require_job(job_id, lock=True)
        job.status = "failed"
        job.last_error = _bounded_error(error)
        return _snapshot(job)

    async def mark_transferred(self, job_id: UUID) -> ImportJobSnapshot:
        job = await self._require_job(job_id, lock=True)
        job.status = "transferred"
        job.last_error = None
        return _snapshot(job)

    async def mark_reindexing(self, job_id: UUID) -> ImportJobSnapshot:
        job = await self._require_job(job_id, lock=True)
        job.status = "reindexing"
        job.last_error = None
        return _snapshot(job)

    async def mark_completed(self, job_id: UUID) -> ImportJobSnapshot:
        job = await self._require_job(job_id, lock=True)
        job.status = "completed"
        job.completed_at = func.now()
        job.last_error = None
        return _snapshot(job)

    async def set_owner_progress_message(
        self,
        *,
        job_id: UUID,
        message_id: int,
    ) -> None:
        await self._session.execute(
            update(ArchiveImportJob)
            .where(ArchiveImportJob.id == job_id)
            .values(owner_progress_message_id=message_id)
        )

    async def mapped_source_ids(
        self,
        *,
        job_id: UUID,
        source_message_ids: tuple[int, ...],
    ) -> set[int]:
        if not source_message_ids:
            return set()
        rows = await self._session.scalars(
            select(ArchiveImportMessageMap.source_message_id).where(
                ArchiveImportMessageMap.job_id == job_id,
                ArchiveImportMessageMap.source_message_id.in_(source_message_ids),
            )
        )
        return {int(value) for value in rows.all()}

    async def record_reconciled_mappings(
        self,
        *,
        job_id: UUID,
        mappings: tuple[tuple[int, int], ...],
    ) -> int:
        if not mappings:
            return 0

        inserted = await self._insert_mappings(job_id=job_id, mappings=mappings)
        if inserted:
            job = await self._require_job(job_id, lock=True)
            job.copied_messages += inserted
            job.reconciled_messages += inserted
        return inserted

    async def record_transfer_batch(
        self,
        *,
        job_id: UUID,
        processed_through_source_id: int,
        processed_count: int,
        skipped_count: int,
        forwarded_mappings: tuple[tuple[int, int], ...],
    ) -> int:
        if processed_count < 0 or skipped_count < 0:
            raise ValueError("batch counts cannot be negative")

        inserted = await self._insert_mappings(
            job_id=job_id,
            mappings=forwarded_mappings,
        )
        job = await self._require_job(job_id, lock=True)
        if processed_through_source_id <= job.last_copied_source_message_id:
            return inserted

        job.last_copied_source_message_id = processed_through_source_id
        job.processed_messages += processed_count
        job.skipped_messages += skipped_count
        job.copied_messages += inserted
        return inserted

    async def list_mappings_after(
        self,
        *,
        job_id: UUID,
        after_source_message_id: int,
        limit: int,
    ) -> tuple[ImportMessageMapping, ...]:
        limit = max(1, min(500, limit))
        rows = (
            await self._session.execute(
                select(ArchiveImportMessageMap)
                .where(
                    ArchiveImportMessageMap.job_id == job_id,
                    ArchiveImportMessageMap.source_message_id
                    > after_source_message_id,
                )
                .order_by(ArchiveImportMessageMap.source_message_id)
                .limit(limit)
            )
        ).scalars().all()
        return tuple(_mapping(row) for row in rows)

    async def mark_reindexed(
        self,
        *,
        job_id: UUID,
        source_message_id: int,
        missing: bool,
    ) -> None:
        job = await self._require_job(job_id, lock=True)

        mapping = await self._session.scalar(
            select(ArchiveImportMessageMap)
            .where(
                ArchiveImportMessageMap.job_id == job_id,
                ArchiveImportMessageMap.source_message_id == source_message_id,
            )
            .with_for_update()
        )
        if mapping is None:
            raise RuntimeError("import mapping disappeared during reindex")

        if not missing and mapping.reindexed_at is None:
            mapping.reindexed_at = func.now()
            job.reindexed_messages += 1
        elif missing:
            job.missing_archive_messages += 1

        if source_message_id > job.last_reindexed_source_message_id:
            job.last_reindexed_source_message_id = source_message_id

    async def max_mapped_archive_message_id(self, job_id: UUID) -> int | None:
        return await self._session.scalar(
            select(func.max(ArchiveImportMessageMap.archive_message_id)).where(
                ArchiveImportMessageMap.job_id == job_id
            )
        )

    async def count_mappings(self, job_id: UUID) -> int:
        value = await self._session.scalar(
            select(func.count(ArchiveImportMessageMap.source_message_id)).where(
                ArchiveImportMessageMap.job_id == job_id
            )
        )
        return int(value or 0)

    async def _insert_mappings(
        self,
        *,
        job_id: UUID,
        mappings: tuple[tuple[int, int], ...],
    ) -> int:
        if not mappings:
            return 0

        values = [
            {
                "job_id": job_id,
                "source_message_id": source_message_id,
                "archive_message_id": archive_message_id,
            }
            for source_message_id, archive_message_id in mappings
        ]
        statement = insert(ArchiveImportMessageMap).values(values)
        statement = statement.on_conflict_do_nothing().returning(
            ArchiveImportMessageMap.source_message_id
        )
        result = await self._session.execute(statement)
        return len(result.scalars().all())

    async def _require_job(
        self,
        job_id: UUID,
        *,
        lock: bool,
    ) -> ArchiveImportJob:
        statement = select(ArchiveImportJob).where(ArchiveImportJob.id == job_id)
        if lock:
            statement = statement.with_for_update()
        job = await self._session.scalar(statement)
        if job is None:
            raise RuntimeError("historical import job not found")
        return job


async def is_bulk_import_active(
    session: AsyncSession,
    archive_channel_id: int,
) -> bool:
    value = await session.scalar(
        select(ArchiveImportJob.id)
        .where(
            ArchiveImportJob.archive_channel_id == archive_channel_id,
            ArchiveImportJob.status.in_(_ACTIVE_BULK_STATUSES),
        )
        .limit(1)
    )
    return value is not None


def _snapshot(job: ArchiveImportJob) -> ImportJobSnapshot:
    return ImportJobSnapshot(
        id=job.id,
        source_channel_id=job.source_channel_id,
        archive_channel_id=job.archive_channel_id,
        status=job.status,
        source_high_watermark_id=job.source_high_watermark_id,
        archive_baseline_message_id=job.archive_baseline_message_id,
        last_copied_source_message_id=job.last_copied_source_message_id,
        last_reindexed_source_message_id=job.last_reindexed_source_message_id,
        source_total_estimate=job.source_total_estimate,
        processed_messages=job.processed_messages,
        copied_messages=job.copied_messages,
        reconciled_messages=job.reconciled_messages,
        skipped_messages=job.skipped_messages,
        reindexed_messages=job.reindexed_messages,
        missing_archive_messages=job.missing_archive_messages,
        owner_progress_message_id=job.owner_progress_message_id,
        started_at=job.started_at,
        completed_at=job.completed_at,
        last_error=job.last_error,
    )


def _mapping(row: ArchiveImportMessageMap) -> ImportMessageMapping:
    return ImportMessageMapping(
        source_message_id=row.source_message_id,
        archive_message_id=row.archive_message_id,
        reindexed_at=row.reindexed_at,
    )


def _bounded_error(error: str) -> str:
    return error[:2000]
