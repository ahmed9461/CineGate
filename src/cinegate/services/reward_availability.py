from __future__ import annotations

from datetime import datetime

from cinegate.db.models import Movie, MovieQuality, RewardSession


def availability_reason(
    reward: RewardSession,
    movie: Movie | None,
    quality: MovieQuality | None,
) -> str | None:
    """Validate the original row/movie/resolution binding, never retarget it."""
    if movie is None or quality is None:
        return "archive_binding_missing"
    if quality.movie_id != reward.movie_id or quality.quality != reward.quality:
        return "archive_binding_changed"
    if movie.status != "indexed":
        return "archive_movie_unsafe"
    if quality.parser_confidence <= 0:
        return "archive_quality_unsafe"
    return None


def preserve_unavailable(
    reward: RewardSession,
    *,
    reason: str,
    now: datetime,
) -> None:
    """Retain earned proof and binding while releasing the active ad slot."""
    reward.status = "unavailable"
    if reward.unavailable_at is None:
        reward.unavailable_at = now
    reward.unavailable_reason = reason
    reward.delivery_started_at = None
