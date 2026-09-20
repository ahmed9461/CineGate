from __future__ import annotations

import asyncio

import pytest

from cinegate.workers.deletion import DeliveryDeletionWorker


class FakeBot:
    async def delete_message(self, *, chat_id: int, message_id: int):
        return True


class FlakyDeliveryService:
    def __init__(self, stop_event: asyncio.Event) -> None:
        self.stop_event = stop_event
        self.claim_calls = 0
        self.recover_send_calls = 0
        self.recover_delete_calls = 0

    async def recover_stale_sends(self) -> int:
        self.recover_send_calls += 1
        return 0

    async def recover_stale_deletions(self) -> int:
        self.recover_delete_calls += 1
        return 0

    async def claim_due_deletions(self, *, limit: int):
        self.claim_calls += 1
        if self.claim_calls == 1:
            raise RuntimeError("temporary database outage")
        self.stop_event.set()
        return ()

    async def mark_deleted(self, delivery_id: int) -> None:
        return None

    async def reschedule_delete(self, delivery_id: int, error: str) -> None:
        return None


@pytest.mark.asyncio
async def test_worker_survives_temporary_database_failure() -> None:
    stop_event = asyncio.Event()
    service = FlakyDeliveryService(stop_event)
    worker = DeliveryDeletionWorker(
        delivery_service=service,  # type: ignore[arg-type]
        bot=FakeBot(),  # type: ignore[arg-type]
        poll_seconds=0.01,
    )

    await asyncio.wait_for(worker.run(stop_event), timeout=1)

    assert service.recover_send_calls == 1
    assert service.recover_delete_calls == 1
    assert service.claim_calls == 2
