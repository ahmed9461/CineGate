from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    status: str
    telegram_message_id: int | None = None
    delete_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class DueDeletion:
    delivery_id: int
    telegram_user_id: int
    telegram_message_id: int
    attempts: int


class DeliveryError(RuntimeError):
    pass


class RewardNotReady(DeliveryError):
    pass
