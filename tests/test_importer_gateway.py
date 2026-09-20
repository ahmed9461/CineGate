from types import SimpleNamespace

import pytest

from cinegate.importer.errors import (
    HistoricalImportError,
    ImportChannelAccessError,
    ImportFloodWaitTooLong,
    UserBotUnauthorized,
)
from cinegate.importer.gateway import HistoricalTelegramGateway


class FakeUnauthorizedClient:
    def __init__(self) -> None:
        self.connected = False
        self.disconnected = False

    async def connect(self) -> None:
        self.connected = True

    async def is_user_authorized(self) -> bool:
        return False

    async def disconnect(self) -> None:
        self.disconnected = True


@pytest.mark.asyncio
async def test_unauthorized_userbot_session_refuses_run() -> None:
    gateway = object.__new__(HistoricalTelegramGateway)
    client = FakeUnauthorizedClient()
    gateway._client = client

    with pytest.raises(UserBotUnauthorized):
        await gateway.connect_authorized()

    assert client.connected
    assert client.disconnected


class FakeFloodWait(Exception):
    def __init__(self, seconds: int) -> None:
        super().__init__(f"wait {seconds}")
        self.seconds = seconds


class FloodThenSuccessClient:
    def __init__(self, waits: list[int]) -> None:
        self.waits = list(waits)
        self.calls = 0

    async def forward_messages(self, *args, **kwargs):
        self.calls += 1
        if self.waits:
            raise FakeFloodWait(self.waits.pop(0))
        return [SimpleNamespace(id=1001), SimpleNamespace(id=1002)]


@pytest.mark.asyncio
async def test_short_flood_wait_sleeps_then_resumes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = object.__new__(HistoricalTelegramGateway)
    gateway._flood_wait_limit = 600
    gateway._client = FloodThenSuccessClient([2])

    sleeps = []

    async def fake_sleep(seconds: int) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(
        "cinegate.importer.gateway.errors.FloodWaitError",
        FakeFloodWait,
    )
    monkeypatch.setattr(
        "cinegate.importer.gateway.asyncio.sleep",
        fake_sleep,
    )

    result = await gateway.forward_batch(
        source=object(),
        archive=object(),
        messages=(SimpleNamespace(id=1), SimpleNamespace(id=2)),
    )

    assert [item.id for item in result] == [1001, 1002]
    assert sleeps == [2]
    assert gateway._client.calls == 2


@pytest.mark.asyncio
async def test_long_flood_wait_stops_without_sleep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = object.__new__(HistoricalTelegramGateway)
    gateway._flood_wait_limit = 600
    gateway._client = FloodThenSuccessClient([601])

    sleeps = []

    async def fake_sleep(seconds: int) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(
        "cinegate.importer.gateway.errors.FloodWaitError",
        FakeFloodWait,
    )
    monkeypatch.setattr(
        "cinegate.importer.gateway.asyncio.sleep",
        fake_sleep,
    )

    with pytest.raises(ImportFloodWaitTooLong) as exc_info:
        await gateway.forward_batch(
            source=object(),
            archive=object(),
            messages=(SimpleNamespace(id=1),),
        )

    assert exc_info.value.seconds == 601
    assert sleeps == []


@pytest.mark.asyncio
async def test_repeated_short_flood_wait_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = object.__new__(HistoricalTelegramGateway)
    gateway._flood_wait_limit = 600
    gateway._client = FloodThenSuccessClient([1, 1, 1, 1])

    async def fake_sleep(seconds: int) -> None:
        return None

    monkeypatch.setattr(
        "cinegate.importer.gateway.errors.FloodWaitError",
        FakeFloodWait,
    )
    monkeypatch.setattr(
        "cinegate.importer.gateway.asyncio.sleep",
        fake_sleep,
    )

    with pytest.raises(HistoricalImportError, match="repeated"):
        await gateway.forward_batch(
            source=object(),
            archive=object(),
            messages=(SimpleNamespace(id=1),),
        )

    assert gateway._client.calls == 4



class FakeEntityClient:
    def __init__(self) -> None:
        self.dialog_calls = 0
        self.entity_calls = []

    async def get_dialogs(self):
        self.dialog_calls += 1
        return []

    async def get_entity(self, channel_id):
        self.entity_calls.append(channel_id)
        return SimpleNamespace(id=channel_id, noforwards=False)


@pytest.mark.asyncio
async def test_private_channel_entity_cache_is_loaded_once() -> None:
    gateway = object.__new__(HistoricalTelegramGateway)
    gateway._dialogs_loaded = False
    gateway._client = FakeEntityClient()

    first = await gateway.resolve_channel(-100111)
    second = await gateway.resolve_channel(-100222)

    assert first.id == -100111
    assert second.id == -100222
    assert gateway._client.dialog_calls == 1
    assert gateway._client.entity_calls == [-100111, -100222]



class ProtectedArchiveClient:
    def __init__(self) -> None:
        self.dialog_calls = 0

    async def get_dialogs(self):
        self.dialog_calls += 1
        return []

    async def get_entity(self, channel_id):
        return SimpleNamespace(
            id=channel_id,
            noforwards=(channel_id == -100222),
        )


@pytest.mark.asyncio
async def test_protected_archive_channel_is_rejected_before_import() -> None:
    gateway = object.__new__(HistoricalTelegramGateway)
    gateway._dialogs_loaded = False
    gateway._client = ProtectedArchiveClient()

    with pytest.raises(ImportChannelAccessError, match="Archive Channel"):
        await gateway.resolve_channels(
            source_channel_id=-100111,
            archive_channel_id=-100222,
        )

    assert gateway._client.dialog_calls == 1
