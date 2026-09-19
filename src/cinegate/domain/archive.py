from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class MediaKind(StrEnum):
    PHOTO = "photo"
    VIDEO = "video"
    DOCUMENT = "document"
    OTHER = "other"


class ParserStyle(StrEnum):
    MODERN = "modern"
    LEGACY = "legacy"


class GroupStatus(StrEnum):
    INDEXED = "indexed"
    ORPHAN = "orphan"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class ArchiveMessage:
    message_id: int
    media_kind: MediaKind
    caption: str | None = None

    def __post_init__(self) -> None:
        if self.message_id <= 0:
            raise ValueError("message_id must be positive")


@dataclass(frozen=True, slots=True)
class ParsedQuality:
    message_id: int
    quality: str
    raw_caption: str
    raw_title: str | None
    normalized_title: str | None
    year: int | None
    confidence: int


@dataclass(frozen=True, slots=True)
class ParsedMovieGroup:
    poster_message_id: int
    raw_poster_caption: str
    raw_title: str
    display_title: str
    normalized_title: str
    year: int | None
    parser_style: ParserStyle
    status: GroupStatus
    poster_confidence: int
    qualities: tuple[ParsedQuality, ...] = ()
    diagnostics: tuple[str, ...] = field(default_factory=tuple)
