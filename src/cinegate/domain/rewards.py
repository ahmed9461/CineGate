from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RewardSessionView:
    id: UUID
    telegram_user_id: int
    movie_id: int
    movie_quality_id: int
    quality: str
    status: str
    expires_at: datetime
    prompt_message_id: int | None
    client_completed_at: datetime | None
    provider_confirmed_at: datetime | None

    @property
    def is_rewarded(self) -> bool:
        return self.status in {"rewarded", "delivering", "delivered"}


class RewardError(RuntimeError):
    pass


class RewardSessionNotFound(RewardError):
    pass


class RewardSessionExpired(RewardError):
    pass


class RewardUserMismatch(RewardError):
    pass


class RewardQualityUnavailable(RewardError):
    pass


class ActiveRewardConflict(RewardError):
    def __init__(self, session: RewardSessionView) -> None:
        super().__init__(
            f"active reward already targets movie={session.movie_id} "
            f"quality={session.quality}"
        )
        self.session = session
