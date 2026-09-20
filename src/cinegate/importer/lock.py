from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager

from sqlalchemy import func, select

from cinegate.db.session import Database
from cinegate.importer.errors import ImportAlreadyRunning


@asynccontextmanager
async def historical_import_lock(
    database: Database,
    *,
    source_channel_id: int,
    archive_channel_id: int,
):
    key = _lock_key(source_channel_id, archive_channel_id)

    async with database.engine.connect() as connection:
        acquired = bool(
            await connection.scalar(select(func.pg_try_advisory_lock(key)))
        )
        if not acquired:
            raise ImportAlreadyRunning(
                "another importer already holds this source/archive lock"
            )

        try:
            yield
        finally:
            await connection.scalar(select(func.pg_advisory_unlock(key)))


def _lock_key(source_channel_id: int, archive_channel_id: int) -> int:
    raw = f"cinegate-import:{source_channel_id}:{archive_channel_id}".encode()
    digest = hashlib.blake2b(raw, digest_size=8).digest()
    return int.from_bytes(digest, byteorder="big", signed=True)
