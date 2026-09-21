from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from cinegate.importer.errors import UserBotUnauthorized
from cinegate.ops import cli as ops_cli


class FakeDatabase:
    instances = []

    def __init__(self, url: str) -> None:
        self.url = url
        self.disposed = False
        FakeDatabase.instances.append(self)

    async def dispose(self) -> None:
        self.disposed = True


class FailingGateway:
    instances = []

    def __init__(self, *, settings, session_path: Path) -> None:
        self.settings = settings
        self.session_path = session_path
        self.disconnected = False
        FailingGateway.instances.append(self)

    async def connect_authorized(self) -> None:
        raise UserBotUnauthorized("not authorized")

    async def disconnect(self) -> None:
        self.disconnected = True


class ExplodingGateway:
    def __init__(self, *, settings, session_path: Path) -> None:
        raise RuntimeError("constructor failed")


@pytest.mark.asyncio
async def test_archive_verify_disposes_database_when_userbot_connect_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cinegate.importer import gateway as gateway_module

    FakeDatabase.instances.clear()
    FailingGateway.instances.clear()

    monkeypatch.setattr(ops_cli, "Database", FakeDatabase)
    monkeypatch.setattr(
        ops_cli,
        "ImporterDatabaseSettings",
        lambda: SimpleNamespace(
            database_url=SecretStr(
                "postgresql+asyncpg://user:password@localhost/cinegate"
            )
        ),
    )
    monkeypatch.setattr(
        ops_cli,
        "ImporterTelegramSettings",
        lambda: SimpleNamespace(
            telegram_api_id=123456,
            telegram_api_hash=SecretStr(
                "0123456789abcdef0123456789abcdef"
            ),
        ),
    )
    monkeypatch.setattr(
        gateway_module,
        "HistoricalTelegramGateway",
        FailingGateway,
    )

    args = SimpleNamespace(
        session=Path("sessions/test"),
        batch_size=100,
    )

    with pytest.raises(UserBotUnauthorized):
        await ops_cli._archive_verify(args)

    assert len(FakeDatabase.instances) == 1
    assert FakeDatabase.instances[0].disposed
    assert len(FailingGateway.instances) == 1
    assert not FailingGateway.instances[0].disconnected


@pytest.mark.asyncio
async def test_archive_verify_disposes_database_when_gateway_init_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cinegate.importer import gateway as gateway_module

    FakeDatabase.instances.clear()
    monkeypatch.setattr(ops_cli, "Database", FakeDatabase)
    monkeypatch.setattr(
        ops_cli,
        "ImporterDatabaseSettings",
        lambda: SimpleNamespace(
            database_url=SecretStr(
                "postgresql+asyncpg://user:password@localhost/cinegate"
            )
        ),
    )
    monkeypatch.setattr(
        ops_cli,
        "ImporterTelegramSettings",
        lambda: SimpleNamespace(
            telegram_api_id=123456,
            telegram_api_hash=SecretStr(
                "0123456789abcdef0123456789abcdef"
            ),
        ),
    )
    monkeypatch.setattr(
        gateway_module,
        "HistoricalTelegramGateway",
        ExplodingGateway,
    )

    args = SimpleNamespace(
        session=Path("sessions/test"),
        batch_size=100,
    )

    with pytest.raises(RuntimeError, match="constructor failed"):
        await ops_cli._archive_verify(args)

    assert len(FakeDatabase.instances) == 1
    assert FakeDatabase.instances[0].disposed
