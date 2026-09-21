from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from aiogram import Bot

from cinegate.db.session import Database
from cinegate.repositories.settings import SettingsRepository

_ALLOWED_UPDATES = (
    "message",
    "callback_query",
    "channel_post",
    "edited_channel_post",
)
_MAX_CONNECTIONS = 1


class WebhookConfigurationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class WebhookStatus:
    expected_url: str
    actual_url: str
    pending_update_count: int
    max_connections: int | None
    allowed_updates: tuple[str, ...]
    last_error_date: int | None
    last_error_message: str | None
    matches_expected: bool


class WebhookOperations:
    def __init__(
        self,
        *,
        database: Database,
        bot: Bot,
        webhook_secret: str,
    ) -> None:
        self._database = database
        self._bot = bot
        self._webhook_secret = webhook_secret

    async def set(self, *, drop_pending_updates: bool = False) -> WebhookStatus:
        expected_url = await self._expected_url()
        await self._bot.set_webhook(
            url=expected_url,
            max_connections=_MAX_CONNECTIONS,
            allowed_updates=list(_ALLOWED_UPDATES),
            drop_pending_updates=drop_pending_updates,
            secret_token=self._webhook_secret,
        )
        return await self.status()

    async def delete(self, *, drop_pending_updates: bool = False) -> None:
        await self._bot.delete_webhook(
            drop_pending_updates=drop_pending_updates,
        )

    async def status(self) -> WebhookStatus:
        expected_url = await self._expected_url()
        info = await self._bot.get_webhook_info()
        actual_updates = tuple(info.allowed_updates or ())

        return WebhookStatus(
            expected_url=expected_url,
            actual_url=info.url or "",
            pending_update_count=int(info.pending_update_count or 0),
            max_connections=info.max_connections,
            allowed_updates=actual_updates,
            last_error_date=info.last_error_date,
            last_error_message=info.last_error_message,
            matches_expected=(
                info.url == expected_url
                and info.max_connections == _MAX_CONNECTIONS
                and set(actual_updates) == set(_ALLOWED_UPDATES)
            ),
        )

    async def _expected_url(self) -> str:
        async with self._database.session() as session:
            public_base_url = await SettingsRepository(session).get(
                "public_base_url"
            )

        if not isinstance(public_base_url, str):
            raise WebhookConfigurationError(
                "public_base_url is not configured"
            )

        normalized = public_base_url.strip().rstrip("/")
        parsed = urlsplit(normalized)
        if parsed.scheme != "https" or not parsed.hostname:
            raise WebhookConfigurationError(
                "public_base_url must be a valid https:// URL"
            )
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise WebhookConfigurationError(
                "public_base_url must be a clean base URL"
            )

        return f"{normalized}/telegram/webhook"
