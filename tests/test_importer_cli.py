from __future__ import annotations

import os

import pytest
import pytest_asyncio
from sqlalchemy import delete

from cinegate.db.models import (
    AppSetting,
    ArchiveImportJob,
    ArchiveImportMessageMap,
)
from cinegate.db.session import Database
from cinegate.importer.cli import _resolve_pair, async_main, build_parser
from cinegate.importer.errors import HistoricalImportError
from cinegate.repositories.import_jobs import ArchiveImportRepository
from cinegate.repositories.settings import SettingsRepository

DATABASE_URL = os.getenv("CINEGATE_DATABASE_URL")
SOURCE_ID = -1001111111111
ARCHIVE_ID = -1002222222222


async def clean(database: Database) -> None:
    async with database.session() as session, session.begin():
        await session.execute(delete(ArchiveImportMessageMap))
        await session.execute(delete(ArchiveImportJob))
        await session.execute(delete(AppSetting))


@pytest_asyncio.fixture
async def database(monkeypatch: pytest.MonkeyPatch) -> Database:
    if not DATABASE_URL:
        pytest.skip("CINEGATE_DATABASE_URL is not configured")

    monkeypatch.setenv("CINEGATE_DATABASE_URL", DATABASE_URL)
    monkeypatch.delenv("CINEGATE_TELEGRAM_API_ID", raising=False)
    monkeypatch.delenv("CINEGATE_TELEGRAM_API_HASH", raising=False)

    database = Database(DATABASE_URL, pool_size=2, max_overflow=0)
    await clean(database)
    try:
        yield database
    finally:
        await clean(database)
        await database.dispose()


def test_cli_exposes_all_historical_import_commands() -> None:
    parser = build_parser()

    for command in ("auth", "run", "transfer", "reindex", "status", "verify"):
        parsed = parser.parse_args([command])
        assert parsed.command == command


@pytest.mark.asyncio
async def test_status_command_needs_database_only(
    database: Database,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async with database.session() as session, session.begin():
        await SettingsRepository(session).set("source_channel_id", SOURCE_ID)
        await SettingsRepository(session).set("archive_channel_id", ARCHIVE_ID)
        repository = ArchiveImportRepository(session)
        job = await repository.get_or_create_job(
            source_channel_id=SOURCE_ID,
            archive_channel_id=ARCHIVE_ID,
        )
        await repository.initialize_snapshot(
            job_id=job.id,
            source_high_watermark_id=500,
            archive_baseline_message_id=100,
            source_total_estimate=450,
        )

    exit_code = await async_main(["status"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert f"job={job.id}" in captured.out
    assert "source_high=500" in captured.out
    assert "processed=0/450" in captured.out


@pytest.mark.asyncio
async def test_status_can_select_job_explicitly_without_channel_settings(
    database: Database,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async with database.session() as session, session.begin():
        repository = ArchiveImportRepository(session)
        job = await repository.get_or_create_job(
            source_channel_id=SOURCE_ID,
            archive_channel_id=ARCHIVE_ID,
        )

    exit_code = await async_main(["status", "--job", str(job.id)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert str(job.id) in captured.out


@pytest.mark.asyncio
async def test_source_archive_equality_is_rejected(database: Database) -> None:
    with pytest.raises(HistoricalImportError, match="must differ"):
        await _resolve_pair(
            database=database,
            source_arg=SOURCE_ID,
            archive_arg=SOURCE_ID,
        )
