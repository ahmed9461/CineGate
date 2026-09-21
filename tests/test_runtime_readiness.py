from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import SQLAlchemyError

from cinegate.runtime import AppRuntime
from cinegate.services.rate_limit import AbuseProtection


class FakeSession:
    def __init__(self, *, fail: bool = False, delay: float = 0.0) -> None:
        self.fail = fail
        self.delay = delay

    async def execute(self, statement):
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise SQLAlchemyError("database unavailable")
        return None


class FakeDatabase:
    def __init__(self, *, fail: bool = False, delay: float = 0.0) -> None:
        self.fail = fail
        self.delay = delay
        self.disposed = False

    @asynccontextmanager
    async def session(self):
        yield FakeSession(fail=self.fail, delay=self.delay)

    async def dispose(self) -> None:
        self.disposed = True


class FakeBotSession:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeBot:
    def __init__(self) -> None:
        self.session = FakeBotSession()


def runtime_for(*, db_fail: bool = False, worker=None) -> AppRuntime:
    return AppRuntime(
        settings=SimpleNamespace(),  # type: ignore[arg-type]
        database=FakeDatabase(fail=db_fail),  # type: ignore[arg-type]
        bot=object(),  # type: ignore[arg-type]
        dispatcher=object(),  # type: ignore[arg-type]
        rewards=object(),  # type: ignore[arg-type]
        delivery=object(),  # type: ignore[arg-type]
        deletion_worker=object(),  # type: ignore[arg-type]
        abuse=AbuseProtection.defaults(),
        worker_task=worker,
    )


@pytest.mark.asyncio
async def test_runtime_ready_requires_started_worker() -> None:
    runtime = runtime_for(worker=None)

    ready, reason = await runtime.check_ready()

    assert not ready
    assert reason == "deletion worker not started"


@pytest.mark.asyncio
async def test_runtime_ready_rejects_stopped_worker() -> None:
    runtime = runtime_for(worker=SimpleNamespace(done=lambda: True))

    ready, reason = await runtime.check_ready()

    assert not ready
    assert reason == "deletion worker stopped"


@pytest.mark.asyncio
async def test_runtime_ready_rejects_database_failure() -> None:
    runtime = runtime_for(
        db_fail=True,
        worker=SimpleNamespace(done=lambda: False),
    )

    ready, reason = await runtime.check_ready()

    assert not ready
    assert reason == "database unavailable"


@pytest.mark.asyncio
async def test_runtime_ready_bounds_a_hung_database_check() -> None:
    runtime = runtime_for(worker=SimpleNamespace(done=lambda: False))
    runtime.database = FakeDatabase(delay=1)  # type: ignore[assignment]
    runtime.readiness_timeout_seconds = 0.01

    ready, reason = await runtime.check_ready()

    assert not ready
    assert reason == "database unavailable"


@pytest.mark.asyncio
async def test_runtime_ready_when_database_and_worker_are_healthy() -> None:
    runtime = runtime_for(
        db_fail=False,
        worker=SimpleNamespace(done=lambda: False),
    )

    ready, reason = await runtime.check_ready()

    assert ready
    assert reason == "ready"


@pytest.mark.asyncio
async def test_runtime_close_releases_resources_after_worker_failure() -> None:
    database = FakeDatabase()
    bot = FakeBot()
    worker = asyncio.get_running_loop().create_future()
    worker.set_exception(RuntimeError("worker failed"))
    runtime = AppRuntime(
        settings=SimpleNamespace(),  # type: ignore[arg-type]
        database=database,  # type: ignore[arg-type]
        bot=bot,  # type: ignore[arg-type]
        dispatcher=object(),  # type: ignore[arg-type]
        rewards=object(),  # type: ignore[arg-type]
        delivery=object(),  # type: ignore[arg-type]
        deletion_worker=object(),  # type: ignore[arg-type]
        abuse=AbuseProtection.defaults(),
        worker_task=worker,
    )

    with pytest.raises(RuntimeError, match="worker failed"):
        await runtime.close()

    assert bot.session.closed
    assert database.disposed
    assert runtime.worker_task is None
