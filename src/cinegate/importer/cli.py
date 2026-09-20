from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

from cinegate.db.session import Database
from cinegate.importer.config import (
    ImporterDatabaseSettings,
    ImporterProgressSettings,
    ImporterSettings,
    ImporterTelegramSettings,
)
from cinegate.importer.errors import HistoricalImportError
from cinegate.importer.gateway import HistoricalTelegramGateway
from cinegate.importer.progress import ImportProgressReporter, render_import_progress
from cinegate.importer.service import HistoricalImportService
from cinegate.repositories.import_jobs import ArchiveImportRepository
from cinegate.repositories.settings import SettingsRepository

_DEFAULT_SESSION = Path("sessions/cinegate_userbot")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m cinegate.importer",
        description="CineGate one-time historical Telegram archive importer.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    auth = subparsers.add_parser(
        "auth",
        help="Interactively authorize the Telegram UserBot session.",
    )
    _add_session_argument(auth)

    for command in ("run", "transfer"):
        item = subparsers.add_parser(
            command,
            help=(
                "Transfer historical messages and reindex."
                if command == "run"
                else "Transfer historical messages only."
            ),
        )
        _add_channel_arguments(item)
        _add_session_argument(item)
        item.add_argument(
            "--batch-size",
            type=int,
            default=25,
            choices=range(1, 101),
            metavar="1..100",
        )
        item.add_argument(
            "--reindex-batch-size",
            type=int,
            default=100,
            choices=range(1, 501),
            metavar="1..500",
        )

    reindex = subparsers.add_parser(
        "reindex",
        help="Resume/replay mapped Archive messages through CineGate indexing.",
    )
    _add_job_selection_arguments(reindex)
    _add_session_argument(reindex)
    reindex.add_argument("--full", action="store_true")
    reindex.add_argument(
        "--reindex-batch-size",
        type=int,
        default=100,
        choices=range(1, 501),
        metavar="1..500",
    )

    status_parser = subparsers.add_parser(
        "status",
        help="Show durable historical-import status without connecting Telegram.",
    )
    _add_job_selection_arguments(status_parser)

    verify = subparsers.add_parser(
        "verify",
        help="Verify stored source→archive mappings without changing Telegram.",
    )
    _add_job_selection_arguments(verify)
    _add_session_argument(verify)
    verify.add_argument(
        "--reindex-batch-size",
        type=int,
        default=100,
        choices=range(1, 501),
        metavar="1..500",
    )

    return parser


async def async_main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        if args.command == "auth":
            return await _auth(args)

        database_settings = ImporterDatabaseSettings()
        database = Database(database_settings.database_url.get_secret_value())
        try:
            if args.command == "status":
                return await _status(database, args)

            settings = ImporterSettings()
            gateway = HistoricalTelegramGateway(
                settings=settings,
                session_path=args.session,
            )
            await gateway.connect_authorized()
            try:
                if args.command in {"run", "transfer"}:
                    return await _run_or_transfer(
                        database=database,
                        gateway=gateway,
                        args=args,
                    )
                if args.command == "reindex":
                    return await _reindex(
                        database=database,
                        gateway=gateway,
                        args=args,
                    )
                if args.command == "verify":
                    return await _verify(
                        database=database,
                        gateway=gateway,
                        args=args,
                    )
            finally:
                await gateway.disconnect()
        finally:
            await database.dispose()
    except (HistoricalImportError, ValidationError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    return 0


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


async def _auth(args) -> int:
    settings = ImporterTelegramSettings()
    gateway = HistoricalTelegramGateway(
        settings=settings,
        session_path=args.session,
    )
    try:
        await gateway.authorize_interactive()
    finally:
        await gateway.disconnect()

    print(f"UserBot session authorized: {args.session}")
    return 0


async def _run_or_transfer(
    *,
    database: Database,
    gateway: HistoricalTelegramGateway,
    args,
) -> int:
    source_channel_id, archive_channel_id = await _resolve_pair(
        database=database,
        source_arg=args.source,
        archive_arg=args.archive,
    )
    reporter = await _build_reporter(database)
    try:
        service = HistoricalImportService(
            database=database,
            gateway=gateway,
            batch_size=args.batch_size,
            reindex_batch_size=args.reindex_batch_size,
            progress_callback=reporter,
        )

        if args.command == "run":
            result = await service.run(
                source_channel_id=source_channel_id,
                archive_channel_id=archive_channel_id,
            )
            job = result.job
        else:
            job = await service.transfer(
                source_channel_id=source_channel_id,
                archive_channel_id=archive_channel_id,
            )

        _print_job_identity(job)
        print(render_import_progress(job))
        return 0
    finally:
        await reporter.close()


async def _reindex(
    *,
    database: Database,
    gateway: HistoricalTelegramGateway,
    args,
) -> int:
    job = await _resolve_job(database, args)
    reporter = await _build_reporter(database)
    try:
        service = HistoricalImportService(
            database=database,
            gateway=gateway,
            reindex_batch_size=args.reindex_batch_size,
            progress_callback=reporter,
        )
        completed = await service.reindex(
            job_id=job.id,
            full=args.full,
        )
        _print_job_identity(completed)
        print(render_import_progress(completed))
        return 0
    finally:
        await reporter.close()


async def _verify(
    *,
    database: Database,
    gateway: HistoricalTelegramGateway,
    args,
) -> int:
    job = await _resolve_job(database, args)
    service = HistoricalImportService(
        database=database,
        gateway=gateway,
        reindex_batch_size=args.reindex_batch_size,
    )
    verification = await service.verify(job_id=job.id)

    _print_job_identity(job)
    print(
        "verify: "
        f"mapped={verification.total_mappings} "
        f"present={verification.present_messages} "
        f"missing={verification.missing_messages} "
        f"mismatch={verification.source_mismatches}"
    )
    return (
        0
        if verification.missing_messages == 0
        and verification.source_mismatches == 0
        else 3
    )


async def _status(database: Database, args) -> int:
    job = await _resolve_job(database, args)
    _print_job_identity(job)
    print(render_import_progress(job))
    if job.source_high_watermark_id is not None:
        print(
            "checkpoint: "
            f"source_high={job.source_high_watermark_id} "
            f"last_copied={job.last_copied_source_message_id} "
            f"last_reindexed={job.last_reindexed_source_message_id}"
        )
    return 0


async def _resolve_pair(
    *,
    database: Database,
    source_arg: int | None,
    archive_arg: int | None,
) -> tuple[int, int]:
    async with database.session() as session:
        repository = SettingsRepository(session)
        source_channel_id = (
            source_arg
            if source_arg is not None
            else await repository.get_int("source_channel_id")
        )
        archive_channel_id = (
            archive_arg
            if archive_arg is not None
            else await repository.get_int("archive_channel_id")
        )

    if source_channel_id is None:
        raise HistoricalImportError(
            "source channel is missing; set source_channel_id in /admin "
            "or pass --source"
        )
    if archive_channel_id is None:
        raise HistoricalImportError(
            "archive channel is missing; set archive_channel_id in /admin "
            "or pass --archive"
        )
    if source_channel_id == archive_channel_id:
        raise HistoricalImportError("source and archive channels must differ")

    return source_channel_id, archive_channel_id


async def _resolve_job(database: Database, args):
    if args.job is not None:
        async with database.session() as session:
            job = await ArchiveImportRepository(session).get_job(args.job)
    else:
        source_channel_id, archive_channel_id = await _resolve_pair(
            database=database,
            source_arg=args.source,
            archive_arg=args.archive,
        )
        async with database.session() as session:
            job = await ArchiveImportRepository(session).get_job_by_pair(
                source_channel_id=source_channel_id,
                archive_channel_id=archive_channel_id,
            )

    if job is None:
        raise HistoricalImportError("historical import job not found")
    return job


async def _build_reporter(database: Database) -> ImportProgressReporter:
    progress_settings = ImporterProgressSettings()
    bot_token = (
        progress_settings.bot_token.get_secret_value()
        if progress_settings.bot_token is not None
        else None
    )
    return ImportProgressReporter(
        database=database,
        bot_token=bot_token,
    )


def _print_job_identity(job) -> None:
    print(
        f"job={job.id} "
        f"source={job.source_channel_id} "
        f"archive={job.archive_channel_id}"
    )


def _add_channel_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source", type=int)
    parser.add_argument("--archive", type=int)


def _add_job_selection_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--job", type=UUID)
    _add_channel_arguments(parser)


def _add_session_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--session",
        type=Path,
        default=_DEFAULT_SESSION,
        help=f"Telethon session base path (default: {_DEFAULT_SESSION})",
    )
