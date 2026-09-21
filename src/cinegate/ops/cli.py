from __future__ import annotations

import argparse
import asyncio
import sys

from aiogram import Bot
from pydantic import ValidationError

from cinegate.config import SecretsSettings
from cinegate.db.session import Database
from cinegate.services.webhook_ops import (
    WebhookConfigurationError,
    WebhookOperations,
    WebhookStatus,
)


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
    actions = webhook.add_subparsers(dest="action", required=True)

    set_parser = actions.add_parser("set")
    set_parser.add_argument(
        "--drop-pending",
        action="store_true",
        help="Explicitly drop Telegram pending updates while setting.",
    )

    actions.add_parser("status")

    delete_parser = actions.add_parser("delete")
    delete_parser.add_argument(
        "--drop-pending",
        action="store_true",
        help="Explicitly drop Telegram pending updates while deleting.",
    )

    return parser


async def async_main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
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
                _print_status(result)
                return 0 if result.matches_expected else 3

            if args.action == "status":
                result = await operations.status()
                _print_status(result)
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
    except (ValidationError, WebhookConfigurationError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    return 0


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


def _print_status(result: WebhookStatus) -> None:
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
