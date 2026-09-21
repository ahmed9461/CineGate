from __future__ import annotations

import os
import subprocess
import sys
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import delete

from cinegate.db.models import AppSetting
from cinegate.db.session import Database
from cinegate.ops.cli import build_parser
from cinegate.repositories.settings import SettingsRepository
from cinegate.services.webhook_ops import (
    WebhookConfigurationError,
    WebhookOperations,
)

DATABASE_URL = os.getenv("CINEGATE_DATABASE_URL")
WEBHOOK_SECRET = "valid_secret"


class FakeBot:
    def __init__(self) -> None:
        self.set_calls = []
        self.delete_calls = []
        self.info = SimpleNamespace(
            url="",
            pending_update_count=0,
            max_connections=None,
            allowed_updates=None,
            last_error_date=None,
            last_error_message=None,
        )

    async def set_webhook(self, **kwargs):
        self.set_calls.append(kwargs)
        self.info = SimpleNamespace(
            url=kwargs["url"],
            pending_update_count=0,
            max_connections=kwargs["max_connections"],
            allowed_updates=kwargs["allowed_updates"],
            last_error_date=None,
            last_error_message=None,
        )
        return True

    async def get_webhook_info(self):
        return self.info

    async def delete_webhook(self, **kwargs):
        self.delete_calls.append(kwargs)
        self.info = SimpleNamespace(
            url="",
            pending_update_count=0,
            max_connections=None,
            allowed_updates=None,
            last_error_date=None,
            last_error_message=None,
        )
        return True


@pytest_asyncio.fixture
async def database() -> Database:
    if not DATABASE_URL:
        pytest.skip("CINEGATE_DATABASE_URL is not configured")

    database = Database(DATABASE_URL, pool_size=2, max_overflow=0)
    async with database.session() as session, session.begin():
        await session.execute(delete(AppSetting))
    try:
        yield database
    finally:
        async with database.session() as session, session.begin():
            await session.execute(delete(AppSetting))
        await database.dispose()


async def set_public_url(database: Database, value: str) -> None:
    async with database.session() as session, session.begin():
        await SettingsRepository(session).set("public_base_url", value)


@pytest.mark.asyncio
async def test_webhook_set_enforces_single_connection_and_allowed_updates(
    database: Database,
) -> None:
    await set_public_url(database, "https://cinegate.example")
    bot = FakeBot()
    operations = WebhookOperations(
        database=database,
        bot=bot,  # type: ignore[arg-type]
        webhook_secret=WEBHOOK_SECRET,
    )

    result = await operations.set()

    assert result.matches_expected
    assert len(bot.set_calls) == 1
    call = bot.set_calls[0]
    assert call["url"] == "https://cinegate.example/telegram/webhook"
    assert call["max_connections"] == 1
    assert call["allowed_updates"] == [
        "message",
        "callback_query",
        "channel_post",
        "edited_channel_post",
    ]
    assert call["secret_token"] == WEBHOOK_SECRET
    assert call["drop_pending_updates"] is False


@pytest.mark.asyncio
async def test_webhook_set_drops_pending_only_when_explicit(
    database: Database,
) -> None:
    await set_public_url(database, "https://cinegate.example")
    bot = FakeBot()
    operations = WebhookOperations(
        database=database,
        bot=bot,  # type: ignore[arg-type]
        webhook_secret=WEBHOOK_SECRET,
    )

    await operations.set(drop_pending_updates=True)

    assert bot.set_calls[0]["drop_pending_updates"] is True


@pytest.mark.asyncio
async def test_webhook_status_detects_configuration_mismatch(
    database: Database,
) -> None:
    await set_public_url(database, "https://cinegate.example")
    bot = FakeBot()
    bot.info = SimpleNamespace(
        url="https://cinegate.example/telegram/webhook",
        pending_update_count=12,
        max_connections=40,
        allowed_updates=["message"],
        last_error_date=123,
        last_error_message="temporary error",
    )
    operations = WebhookOperations(
        database=database,
        bot=bot,  # type: ignore[arg-type]
        webhook_secret=WEBHOOK_SECRET,
    )

    result = await operations.status()

    assert not result.matches_expected
    assert result.pending_update_count == 12
    assert result.max_connections == 40
    assert result.allowed_updates == ("message",)
    assert result.last_error_message == "temporary error"


@pytest.mark.asyncio
async def test_webhook_delete_keeps_pending_updates_by_default(
    database: Database,
) -> None:
    await set_public_url(database, "https://cinegate.example")
    bot = FakeBot()
    operations = WebhookOperations(
        database=database,
        bot=bot,  # type: ignore[arg-type]
        webhook_secret=WEBHOOK_SECRET,
    )

    await operations.delete()

    assert bot.delete_calls == [{"drop_pending_updates": False}]


@pytest.mark.asyncio
async def test_webhook_operations_require_clean_https_public_url(
    database: Database,
) -> None:
    await set_public_url(database, "http://cinegate.example")
    operations = WebhookOperations(
        database=database,
        bot=FakeBot(),  # type: ignore[arg-type]
        webhook_secret=WEBHOOK_SECRET,
    )

    with pytest.raises(WebhookConfigurationError, match="https"):
        await operations.status()


def test_ops_cli_exposes_webhook_commands() -> None:
    parser = build_parser()

    for action in ("set", "status", "delete"):
        parsed = parser.parse_args(["webhook", action])
        assert parsed.area == "webhook"
        assert parsed.action == action



def test_ops_cli_exposes_archive_verify_command() -> None:
    parser = build_parser()
    parsed = parser.parse_args(["archive", "verify", "--batch-size", "50"])

    assert parsed.area == "archive"
    assert parsed.action == "verify"
    assert parsed.batch_size == 50



@pytest.mark.asyncio
async def test_webhook_status_accepts_allowed_updates_in_different_order(
    database: Database,
) -> None:
    await set_public_url(database, "https://cinegate.example")
    bot = FakeBot()
    bot.info = SimpleNamespace(
        url="https://cinegate.example/telegram/webhook",
        pending_update_count=0,
        max_connections=1,
        allowed_updates=[
            "edited_channel_post",
            "channel_post",
            "callback_query",
            "message",
        ],
        last_error_date=None,
        last_error_message=None,
    )
    operations = WebhookOperations(
        database=database,
        bot=bot,  # type: ignore[arg-type]
        webhook_secret=WEBHOOK_SECRET,
    )

    result = await operations.status()

    assert result.matches_expected



@pytest.mark.asyncio
async def test_webhook_status_accepts_allowed_updates_in_different_order(
    database: Database,
) -> None:
    await set_public_url(database, "https://cinegate.example")
    bot = FakeBot()
    bot.info = SimpleNamespace(
        url="https://cinegate.example/telegram/webhook",
        pending_update_count=0,
        max_connections=1,
        allowed_updates=[
            "edited_channel_post",
            "channel_post",
            "callback_query",
            "message",
        ],
        last_error_date=None,
        last_error_message=None,
    )
    operations = WebhookOperations(
        database=database,
        bot=bot,  # type: ignore[arg-type]
        webhook_secret=WEBHOOK_SECRET,
    )

    result = await operations.status()

    assert result.matches_expected



def test_webhook_ops_cli_import_does_not_load_optional_telethon() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "import cinegate.ops.cli; "
                "assert 'telethon' not in sys.modules"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
