from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert

from cinegate.db.models import (
    AppSetting,
    Delivery,
    MessageTemplate,
    Movie,
    MovieQuality,
    RewardSession,
    UserSearchSession,
)
from cinegate.db.session import Database
from cinegate.domain.delivery import DeliveryResult
from cinegate.services.reward_sessions import RewardSessionService
from cinegate.web.app import create_app

DATABASE_URL = os.getenv("CINEGATE_DATABASE_URL")
BOT_TOKEN = "123456789:TEST_TOKEN_FOR_CINEGATE"
CALLBACK_SECRET = "a" * 40
USER_ID = 123456789
ARCHIVE_CHANNEL_ID = -1001234567890


class FakeDispatcher:
    async def feed_update(self, bot, update) -> None:
        return None


class FakeDelivery:
    def __init__(self) -> None:
        self.calls = []

    async def deliver(self, reward_id):
        self.calls.append(reward_id)
        return DeliveryResult(
            status="delivered",
            telegram_message_id=9001,
        )


class FakeRuntime:
    def __init__(self, database: Database, rewards: RewardSessionService) -> None:
        self.database = database
        self.rewards = rewards
        self.delivery = FakeDelivery()
        self.settings = SimpleNamespace(
            bot_token=SecretStr(BOT_TOKEN),
            webhook_secret=SecretStr("webhook-secret"),
            adsgram_callback_secret=SecretStr(CALLBACK_SECRET),
        )
        self.bot = object()
        self.dispatcher = FakeDispatcher()
        self.started = False
        self.closed = False

    async def start(self) -> None:
        self.started = True

    async def close(self) -> None:
        self.closed = True


async def clean_database(database: Database) -> None:
    async with database.session() as session, session.begin():
        await session.execute(delete(Delivery))
        await session.execute(delete(RewardSession))
        await session.execute(delete(UserSearchSession))
        await session.execute(delete(MovieQuality))
        await session.execute(delete(Movie))
        await session.execute(delete(AppSetting))
        await session.execute(delete(MessageTemplate))


@pytest_asyncio.fixture
async def setup():
    if not DATABASE_URL:
        pytest.skip("CINEGATE_DATABASE_URL is not configured")

    database = Database(DATABASE_URL, pool_size=3, max_overflow=0)
    await clean_database(database)

    async with database.session() as session, session.begin():
        movie = Movie(
            archive_channel_id=ARCHIVE_CHANNEL_ID,
            poster_message_id=100,
            display_title="Interstellar",
            normalized_title="interstellar",
            year=2014,
            parser_style="modern",
            status="indexed",
            raw_poster_caption="الفيلم: Interstellar",
            parser_confidence=95,
        )
        session.add(movie)
        await session.flush()
        quality = MovieQuality(
            movie_id=movie.id,
            archive_channel_id=ARCHIVE_CHANNEL_ID,
            archive_message_id=101,
            quality="720p",
            raw_caption="Interstellar 2014 #720p",
            extracted_title="Interstellar",
            normalized_title="interstellar",
            extracted_year=2014,
            parser_confidence=95,
        )
        session.add(quality)
        await session.flush()
        movie_id = movie.id

    rewards = RewardSessionService(database)
    reward, _ = await rewards.get_or_create(
        telegram_user_id=USER_ID,
        movie_id=movie_id,
        quality="720p",
    )
    runtime = FakeRuntime(database, rewards)
    app = create_app(lambda: runtime)

    try:
        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport,
                base_url="http://test",
            ) as client:
                yield database, runtime, reward, client
    finally:
        await clean_database(database)
        await database.dispose()


def signed_init_data() -> str:
    now = datetime.now(UTC)
    values = {
        "auth_date": str(int(now.timestamp())),
        "query_id": "AAEAAAE",
        "user": json.dumps(
            {
                "id": USER_ID,
                "first_name": "Test",
                "username": "cinegate_test",
            },
            separators=(",", ":"),
        ),
    }
    data_check = "\n".join(
        f"{key}={values[key]}" for key in sorted(values)
    )
    secret_key = hmac.new(
        b"WebAppData",
        BOT_TOKEN.encode(),
        hashlib.sha256,
    ).digest()
    values["hash"] = hmac.new(
        secret_key,
        data_check.encode(),
        hashlib.sha256,
    ).hexdigest()
    return urlencode(values)


async def set_setting(database: Database, key: str, value) -> None:
    async with database.session() as session, session.begin():
        statement = insert(AppSetting).values(key=key, value=value)
        statement = statement.on_conflict_do_update(
            index_elements=[AppSetting.key],
            set_={"value": statement.excluded.value},
        )
        await session.execute(statement)


@pytest.mark.asyncio
async def test_reward_page_requires_adsgram_block_id(setup) -> None:
    _database, _runtime, reward, client = setup

    response = await client.get(f"/miniapp/reward/{reward.id}")

    assert response.status_code == 503
    assert "لم يتم إعداد شبكة الإعلانات" in response.text


@pytest.mark.asyncio
async def test_reward_page_contains_telegram_and_adsgram_sdk(setup) -> None:
    database, _runtime, reward, client = setup
    await set_setting(database, "adsgram_block_id", "12345")

    response = await client.get(f"/miniapp/reward/{reward.id}")

    assert response.status_code == 200
    assert "telegram-web-app.js" in response.text
    assert "sad.adsgram.ai/js/sad.min.js" in response.text
    assert 'const blockId = "12345"' in response.text
    assert str(reward.id) in response.text


@pytest.mark.asyncio
async def test_client_completion_alone_does_not_deliver(setup) -> None:
    _database, runtime, reward, client = setup

    response = await client.post(
        f"/api/rewards/{reward.id}/claim",
        json={"init_data": signed_init_data()},
    )

    assert response.status_code == 202
    assert response.json()["status"] == "waiting_provider"
    assert runtime.delivery.calls == []


@pytest.mark.asyncio
async def test_wrong_provider_secret_is_rejected(setup) -> None:
    _database, _runtime, _reward, client = setup

    response = await client.get(
        f"/providers/adsgram/reward/{'b' * 40}",
        params={"userid": USER_ID},
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_provider_then_client_triggers_delivery(setup) -> None:
    _database, runtime, reward, client = setup

    provider = await client.get(
        f"/providers/adsgram/reward/{CALLBACK_SECRET}",
        params={"userid": USER_ID},
    )
    assert provider.status_code == 204
    assert runtime.delivery.calls == []

    claim = await client.post(
        f"/api/rewards/{reward.id}/claim",
        json={"init_data": signed_init_data()},
    )

    assert claim.status_code == 200
    assert claim.json()["status"] == "delivered"
    assert runtime.delivery.calls == [reward.id]


@pytest.mark.asyncio
async def test_provider_callback_without_active_session_is_harmless(setup) -> None:
    database, _runtime, reward, client = setup

    async with database.session() as session, session.begin():
        row = await session.get(RewardSession, reward.id)
        row.status = "expired"

    response = await client.get(
        f"/providers/adsgram/reward/{CALLBACK_SECRET}",
        params={"userid": USER_ID},
    )

    assert response.status_code == 204



@pytest.mark.asyncio
async def test_unknown_reward_page_returns_404(setup) -> None:
    _database, _runtime, _reward, client = setup
    unknown_id = "00000000-0000-0000-0000-000000000001"

    response = await client.get(f"/miniapp/reward/{unknown_id}")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_expired_reward_page_returns_410(setup) -> None:
    database, _runtime, reward, client = setup

    async with database.session() as session, session.begin():
        row = await session.get(RewardSession, reward.id)
        assert row is not None
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)

    response = await client.get(f"/miniapp/reward/{reward.id}")

    assert response.status_code == 410


@pytest.mark.asyncio
async def test_invalid_client_signature_is_rejected_by_endpoint(setup) -> None:
    _database, _runtime, reward, client = setup

    response = await client.post(
        f"/api/rewards/{reward.id}/claim",
        json={"init_data": "auth_date=1&hash=invalid"},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_provider_callback_can_be_disabled(setup) -> None:
    _database, runtime, _reward, client = setup
    runtime.settings.adsgram_callback_secret = None

    response = await client.get(
        f"/providers/adsgram/reward/{CALLBACK_SECRET}",
        params={"userid": USER_ID},
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_client_then_provider_triggers_delivery(setup) -> None:
    _database, runtime, reward, client = setup

    claim = await client.post(
        f"/api/rewards/{reward.id}/claim",
        json={"init_data": signed_init_data()},
    )
    assert claim.status_code == 202
    assert runtime.delivery.calls == []

    provider = await client.get(
        f"/providers/adsgram/reward/{CALLBACK_SECRET}",
        params={"userid": USER_ID},
    )

    assert provider.status_code == 204
    assert runtime.delivery.calls == [reward.id]



@pytest.mark.asyncio
async def test_adsgram_block_id_is_escaped_before_embedding_in_script(setup) -> None:
    database, _runtime, reward, client = setup
    malicious = "</script><script>alert(1)</script>"
    await set_setting(database, "adsgram_block_id", malicious)

    response = await client.get(f"/miniapp/reward/{reward.id}")

    assert response.status_code == 200
    assert malicious not in response.text
    assert "\\u003c/script\\u003e" in response.text
