from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from aiogram import Bot
from pydantic import ValidationError

from cinegate.config import SecretsSettings
from cinegate.db.session import Database
from cinegate.importer.config import (
    ImporterDatabaseSettings,
    ImporterTelegramSettings,
)
from cinegate.importer.errors import HistoricalImportError
from cinegate.importer.gateway import HistoricalTelegramGateway
from cinegate.services.archive_integrity import (
    ArchiveIntegrityAuditService,
    ArchiveIntegrityReport,
)
from cinegate.services.webhook_ops import (
    WebhookConfigurationError,
    WebhookOperations,
    WebhookStatus,
)

_DEFAULT_USERBOT_SESSION = Path("sessions/cinegate_userbot")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m cinegate.ops",
        description="CineGate launch/deployment operations.",
    )
    subparsers = parser.add_subparsers(dest="area", required=True)

    webhook = subparsers.add_parser(
        "webhook",
        help="Manage Telegram webhook registration.",
    )
    webhook_actions = webhook.add_subparsers(
        dest="action",
        required=True,
    )

    set_parser = webhook_actions.add_parser("set")
    set_parser.add_argument(
        "--drop-pending",
        action="store_true",
        help="Explicitly drop Telegram pending updates while setting.",
    )

    webhook_actions.add_parser("status")

    delete_parser = webhook_actions.add_parser("delete")
    delete_parser.add_argument(
        "--drop-pending",
        action="store_true",
        help="Explicitly drop Telegram pending updates while deleting.",
    )

    archive = subparsers.add_parser(
        "archive",
        help="Read-only Archive integrity operations.",
    )
    archive_actions = archive.add_subparsers(
        dest="action",
        required=True,
    )
    verify = archive_actions.add_parser(
        "verify",
        help="Verify indexed Telegram Archive references.",
    )
    verify.add_argument(
        "--session",
        type=Path,
        default=_DEFAULT_USERBOT_SESSION,
    )
    verify.add_argument(
        "--batch-size",
        type=int,
        default=100,
        choices=range(1, 501),
        metavar="1..500",
    )

    return parser


async def async_main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        if args.area == "webhook":
            return await _webhook_command(args)
        if args.area == "archive" and args.action == "verify":
            return await _archive_verify(args)
    except (
        HistoricalImportError,
        ValidationError,
        WebhookConfigurationError,
        ValueError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    return 0


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


async def _webhook_command(args) -> int:
    settings = SecretsSettings()
    database = Database(settings.database_url.get_secret_value())
    bot = Bot(token=settings.bot_token.get_secret_value())
    try:
        operations = WebhookOperations(
            database=database,
            bot=bot,
            webhook_secret=settings.webhook_secret.get_secret_value(),
        )

        if args.action == "set":
            result = await operations.set(
                drop_pending_updates=args.drop_pending,
            )
            _print_webhook_status(result)
            return 0 if result.matches_expected else 3

        if args.action == "status":
            result = await operations.status()
            _print_webhook_status(result)
            return 0 if result.matches_expected else 3

        if args.action == "delete":
            await operations.delete(
                drop_pending_updates=args.drop_pending,
            )
            print("Webhook deleted.")
            return 0
    finally:
        await bot.session.close()
        await database.dispose()

    return 0


async def _archive_verify(args) -> int:
    database_settings = ImporterDatabaseSettings()
    telegram_settings = ImporterTelegramSettings()
    database = Database(
        database_settings.database_url.get_secret_value()
    )
    gateway = HistoricalTelegramGateway(
        settings=telegram_settings,
        session_path=args.session,
    )

    connected = False
    try:
        await gateway.connect_authorized()
        connected = True
        report = await ArchiveIntegrityAuditService(
            database=database,
            gateway=gateway,
            batch_size=args.batch_size,
        ).verify()
        _print_archive_integrity(report)
        return 0 if report.ok else 3
    finally:
        if connected:
            await gateway.disconnect()
        await database.dispose()


def _print_webhook_status(result: WebhookStatus) -> None:
    print(f"url={result.actual_url or '-'}")
    print(f"expected_url={result.expected_url}")
    print(f"pending_updates={result.pending_update_count}")
    print(f"max_connections={result.max_connections}")
    print(
        "allowed_updates="
        + ",".join(result.allowed_updates)
    )
    if result.last_error_date is not None:
        print(f"last_error_date={result.last_error_date}")
    if result.last_error_message:
        print(f"last_error={result.last_error_message[:500]}")
    print(
        "configuration="
        + ("ok" if result.matches_expected else "mismatch")
    )


def _print_archive_integrity(result: ArchiveIntegrityReport) -> None:
    print(f"checked_posters={result.checked_posters}")
    print(f"checked_qualities={result.checked_qualities}")
    print(f"missing_posters={result.missing_posters}")
    print(f"missing_qualities={result.missing_qualities}")

    for item in result.missing_examples:
        print(
            f"missing kind={item.kind} "
            f"row_id={item.row_id} "
            f"archive_message_id={item.archive_message_id}"
        )

    print("integrity=" + ("ok" if result.ok else "missing_references"))
