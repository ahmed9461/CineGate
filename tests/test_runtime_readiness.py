from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import SQLAlchemyError

from cinegate.runtime import AppRuntime
from cinegate.services.rate_limit import AbuseProtection


class FakeSession:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    async def execute(self, statement):
        if self.fail:
            raise SQLAlchemyError("database unavailable")
        return None


class FakeDatabase:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    @asynccontextmanager
    async def session(self):
        yield FakeSession(fail=self.fail)


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
async def test_runtime_ready_when_database_and_worker_are_healthy() -> None:
    runtime = runtime_for(
        db_fail=False,
        worker=SimpleNamespace(done=lambda: False),
    )

    ready, reason = await runtime.check_ready()

    assert ready
    assert reason == "ready"
