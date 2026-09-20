from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

from telethon import TelegramClient, errors

from cinegate.importer.config import ImporterSettings, ImporterTelegramSettings
from cinegate.importer.errors import (
    HistoricalImportError,
    ImportChannelAccessError,
    ImportFloodWaitTooLong,
    SourceForwardingRestricted,
    UserBotUnauthorized,
)

_DEFAULT_FLOOD_WAIT_LIMIT = 600


class HistoricalTelegramGateway:
    """Thin Telethon boundary used only by the historical importer."""

    def __init__(
        self,
        *,
        settings: ImporterSettings | ImporterTelegramSettings,
        session_path: Path,
        flood_wait_limit: int = _DEFAULT_FLOOD_WAIT_LIMIT,
    ) -> None:
        if flood_wait_limit <= 0:
            raise ValueError("flood_wait_limit must be positive")

        session_path.parent.mkdir(parents=True, exist_ok=True)
        self._session_path = session_path
        self._flood_wait_limit = flood_wait_limit
        self._dialogs_loaded = False
        self._client = TelegramClient(
            str(session_path),
            settings.telegram_api_id,
            settings.telegram_api_hash.get_secret_value(),
            flood_sleep_threshold=flood_wait_limit,
            request_retries=5,
            connection_retries=5,
            auto_reconnect=True,
            receive_updates=False,
        )

    @property
    def session_path(self) -> Path:
        return self._session_path

    async def authorize_interactive(self) -> None:
        await self._client.start()
        if not await self._client.is_user_authorized():
            raise UserBotUnauthorized("Telegram UserBot authorization failed")

    async def connect_authorized(self) -> None:
        await self._client.connect()
        if not await self._client.is_user_authorized():
            await self._client.disconnect()
            raise UserBotUnauthorized(
                "UserBot session is not authorized; run importer auth first"
            )

    async def disconnect(self) -> None:
        await self._client.disconnect()

    async def resolve_channel(self, channel_id: int) -> Any:
        await self._ensure_entity_cache()
        try:
            return await self._client.get_entity(channel_id)
        except (ValueError, errors.RPCError) as exc:
            raise ImportChannelAccessError(
                f"could not resolve Telegram channel {channel_id}"
            ) from exc

    async def _ensure_entity_cache(self) -> None:
        if getattr(self, "_dialogs_loaded", False):
            return
        # Populate entity cache once so marked private channel IDs can resolve
        # reliably without repeatedly fetching the full dialog list.
        await self._client.get_dialogs()
        self._dialogs_loaded = True

    async def resolve_channels(
        self,
        *,
        source_channel_id: int,
        archive_channel_id: int,
    ) -> tuple[Any, Any]:
        if source_channel_id == archive_channel_id:
            raise ImportChannelAccessError("source and archive channels must differ")

        source = await self.resolve_channel(source_channel_id)
        archive = await self.resolve_channel(archive_channel_id)

        if bool(getattr(source, "noforwards", False)):
            raise SourceForwardingRestricted(
                "source channel forwarding protection is enabled; "
                "disable it temporarily as the authorized owner and resume"
            )
        if bool(getattr(archive, "noforwards", False)):
            raise ImportChannelAccessError(
                "Archive Channel content protection must be disabled so "
                "CineGate can later copy movie files to users"
            )

        return source, archive

    async def latest_message_id(self, entity: Any) -> int:
        messages = await self._client.get_messages(entity, limit=1)
        if not messages:
            return 0
        return int(messages[0].id)

    async def total_message_estimate(self, entity: Any) -> int:
        messages = await self._client.get_messages(entity, limit=0)
        return int(getattr(messages, "total", 0) or 0)

    async def iter_source_messages(
        self,
        entity: Any,
        *,
        after_message_id: int,
        high_watermark_id: int,
    ) -> AsyncIterator[Any]:
        async for message in self._client.iter_messages(
            entity,
            reverse=True,
            min_id=max(0, after_message_id),
        ):
            message_id = int(getattr(message, "id", 0) or 0)
            if message_id > high_watermark_id:
                break
            yield message

    async def iter_archive_messages_after(
        self,
        entity: Any,
        *,
        after_message_id: int,
    ) -> AsyncIterator[Any]:
        async for message in self._client.iter_messages(
            entity,
            reverse=True,
            min_id=max(0, after_message_id),
        ):
            yield message

    async def forward_batch(
        self,
        *,
        source: Any,
        archive: Any,
        messages: Sequence[Any],
    ) -> tuple[Any, ...]:
        if not messages:
            return ()

        flood_retries = 0
        while True:
            try:
                forwarded = await self._client.forward_messages(
                    archive,
                    list(messages),
                    from_peer=source,
                    silent=True,
                )
                break
            except errors.ChatForwardsRestrictedError as exc:
                raise SourceForwardingRestricted(
                    "Telegram rejected forwarding because source protection is enabled"
                ) from exc
            except errors.FloodWaitError as exc:
                seconds = int(exc.seconds)
                if seconds > self._flood_wait_limit:
                    raise ImportFloodWaitTooLong(seconds) from exc

                flood_retries += 1
                if flood_retries > 3:
                    raise HistoricalImportError(
                        "repeated Telegram FloodWait prevented bounded forwarding"
                    ) from exc
                await asyncio.sleep(seconds)
            except (
                errors.ChatWriteForbiddenError,
                errors.ChannelPrivateError,
            ) as exc:
                raise ImportChannelAccessError(
                    "UserBot cannot write to or access the Archive Channel"
                ) from exc
            except errors.RPCError as exc:
                raise HistoricalImportError(
                    f"Telegram forwarding failed: {type(exc).__name__}"
                ) from exc

        if forwarded is None:
            return ()
        if isinstance(forwarded, list):
            return tuple(forwarded)
        return (forwarded,)

    async def get_messages_by_ids(
        self,
        entity: Any,
        message_ids: Sequence[int],
    ) -> tuple[Any | None, ...]:
        if not message_ids:
            return ()

        result = await self._client.get_messages(
            entity,
            ids=list(message_ids),
        )
        if isinstance(result, list):
            return tuple(result)
        return (result,)
