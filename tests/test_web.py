from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient
from pydantic import SecretStr

from cinegate.web.app import create_app


class FakeDispatcher:
    def __init__(self) -> None:
        self.updates = []

    async def feed_update(self, bot, update) -> None:
        self.updates.append((bot, update))


class FakeRuntime:
    def __init__(self) -> None:
        self.settings = SimpleNamespace(webhook_secret=SecretStr("webhook-secret"))
        self.bot = object()
        self.dispatcher = FakeDispatcher()
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def client_for(runtime: FakeRuntime) -> TestClient:
    return TestClient(create_app(lambda: runtime))


def test_health_endpoint_and_runtime_shutdown() -> None:
    runtime = FakeRuntime()

    with client_for(runtime) as client:
        response = client.get("/healthz")
        assert not runtime.closed

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert runtime.closed


def test_webhook_accepts_valid_secret_and_dispatches_once() -> None:
    runtime = FakeRuntime()

    with client_for(runtime) as client:
        response = client.post(
            "/telegram/webhook",
            headers={"X-Telegram-Bot-Api-Secret-Token": "webhook-secret"},
            json={"update_id": 123},
        )

    assert response.status_code == 200
    assert len(runtime.dispatcher.updates) == 1
    assert runtime.dispatcher.updates[0][1].update_id == 123


def test_webhook_rejects_missing_secret() -> None:
    runtime = FakeRuntime()

    with client_for(runtime) as client:
        response = client.post("/telegram/webhook", json={"update_id": 1})

    assert response.status_code == 403
    assert runtime.dispatcher.updates == []


def test_webhook_rejects_wrong_secret() -> None:
    runtime = FakeRuntime()

    with client_for(runtime) as client:
        response = client.post(
            "/telegram/webhook",
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
            json={"update_id": 1},
        )

    assert response.status_code == 403
    assert runtime.dispatcher.updates == []


def test_webhook_rejects_invalid_json() -> None:
    runtime = FakeRuntime()

    with client_for(runtime) as client:
        response = client.post(
            "/telegram/webhook",
            headers={
                "X-Telegram-Bot-Api-Secret-Token": "webhook-secret",
                "Content-Type": "application/json",
            },
            content=b"{",
        )

    assert response.status_code == 400
    assert runtime.dispatcher.updates == []


def test_webhook_rejects_invalid_update_shape() -> None:
    runtime = FakeRuntime()

    with client_for(runtime) as client:
        response = client.post(
            "/telegram/webhook",
            headers={"X-Telegram-Bot-Api-Secret-Token": "webhook-secret"},
            json={},
        )

    assert response.status_code == 400
    assert runtime.dispatcher.updates == []
