from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class IndexAction(StrEnum):
    IGNORED = "ignored"
    POSTER_UPSERTED = "poster_upserted"
    QUALITY_UPSERTED = "quality_upserted"
    DUPLICATE = "duplicate"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class ArchiveIndexResult:
    action: IndexAction
    movie_id: int | None = None
    display_title: str | None = None
    quality_count: int = 0
    owner_notification_message_id: int | None = None
    owner_notification_quality_count: int = 0
    diagnostic: str | None = None

    @property
    def should_notify_owner(self) -> bool:
        return (
            self.movie_id is not None
            and self.quality_count > self.owner_notification_quality_count
        )
