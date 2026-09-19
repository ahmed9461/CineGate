from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MovieSearchResult:
    movie_id: int
    display_title: str
    year: int | None
    score: float


@dataclass(frozen=True, slots=True)
class MovieView:
    movie_id: int
    archive_channel_id: int
    poster_message_id: int
    display_title: str
    year: int | None
    qualities: tuple[str, ...]


class SearchQueryError(ValueError):
    """Raised when a user search query violates bounded input rules."""
