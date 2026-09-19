from __future__ import annotations

from sqlalchemy import exists, select

from cinegate.db.models import Movie, MovieQuality
from cinegate.db.session import Database
from cinegate.domain.search import MovieSearchResult, MovieView, SearchQueryError
from cinegate.repositories.settings import SettingsRepository
from cinegate.services.text import extract_release_year, normalize_title

_MAX_RAW_QUERY_LENGTH = 128
_DEFAULT_RESULT_LIMIT = 6
_MAX_RESULT_LIMIT = 10
_DEFAULT_SIMILARITY_THRESHOLD = 0.32
_MIN_SIMILARITY_THRESHOLD = 0.15
_MAX_SIMILARITY_THRESHOLD = 0.95
_MAX_CANDIDATES = 50

_QUALITY_ORDER = {
    "480p": 480,
    "720p": 720,
    "1080p": 1080,
    "2160p": 2160,
    "4k": 2161,
}


class MovieSearchService:
    """Bounded PostgreSQL trigram search across canonical and quality titles."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def search(self, raw_query: str) -> tuple[MovieSearchResult, ...]:
        query = raw_query.strip()
        if not query:
            return ()
        if len(query) > _MAX_RAW_QUERY_LENGTH:
            raise SearchQueryError(
                f"search query exceeds {_MAX_RAW_QUERY_LENGTH} characters"
            )

        normalized = normalize_title(query)
        if not normalized:
            return ()

        requested_year = extract_release_year(query)

        async with self._database.session() as session:
            settings = await SettingsRepository(session).get_many(
                ("search_result_limit", "search_similarity_threshold")
            )
            result_limit = _bounded_result_limit(settings.get("search_result_limit"))
            threshold = _bounded_threshold(
                settings.get("search_similarity_threshold")
            )
            candidate_limit = min(max(result_limit * 5, 20), _MAX_CANDIDATES)

            canonical_distance = Movie.normalized_title.op("<->")(normalized).label(
                "distance"
            )
            canonical_rows = (
                await session.execute(
                    select(
                        Movie.id,
                        Movie.display_title,
                        Movie.year,
                        Movie.normalized_title.label("matched_title"),
                        canonical_distance,
                    )
                    .where(
                        Movie.status == "indexed",
                        exists(
                            select(MovieQuality.id).where(
                                MovieQuality.movie_id == Movie.id
                            )
                        ),
                    )
                    .order_by(canonical_distance, Movie.id)
                    .limit(candidate_limit)
                )
            ).all()

            alias_distance = MovieQuality.normalized_title.op("<->")(normalized).label(
                "distance"
            )
            alias_rows = (
                await session.execute(
                    select(
                        Movie.id,
                        Movie.display_title,
                        Movie.year,
                        MovieQuality.normalized_title.label("matched_title"),
                        alias_distance,
                    )
                    .join(MovieQuality, MovieQuality.movie_id == Movie.id)
                    .where(
                        Movie.status == "indexed",
                        MovieQuality.normalized_title.is_not(None),
                    )
                    .order_by(alias_distance, Movie.id, MovieQuality.id)
                    .limit(candidate_limit)
                )
            ).all()

        best_by_movie: dict[
            int,
            tuple[tuple[int, int, float, str, int], MovieSearchResult],
        ] = {}

        for row in (*canonical_rows, *alias_rows):
            matched_title = row.matched_title
            if not matched_title:
                continue

            similarity = max(0.0, min(1.0, 1.0 - float(row.distance)))
            category = _match_category(
                query=normalized,
                candidate=matched_title,
                similarity=similarity,
                threshold=threshold,
            )
            if category is None:
                continue

            year_penalty = (
                0
                if requested_year is None or row.year == requested_year
                else 1
            )
            rank = (
                category,
                year_penalty,
                -similarity,
                row.display_title.casefold(),
                row.id,
            )
            result = MovieSearchResult(
                movie_id=row.id,
                display_title=row.display_title,
                year=row.year,
                score=similarity,
            )

            previous = best_by_movie.get(row.id)
            if previous is None or rank < previous[0]:
                best_by_movie[row.id] = (rank, result)

        ranked = sorted(best_by_movie.values(), key=lambda item: item[0])
        return tuple(result for _, result in ranked[:result_limit])

    async def get_results_by_ids(
        self,
        movie_ids: tuple[int, ...],
    ) -> tuple[MovieSearchResult, ...]:
        if not movie_ids:
            return ()

        async with self._database.session() as session:
            rows = (
                await session.execute(
                    select(
                        Movie.id,
                        Movie.display_title,
                        Movie.year,
                    ).where(
                        Movie.id.in_(movie_ids),
                        Movie.status == "indexed",
                    )
                )
            ).all()

        by_id = {
            row.id: MovieSearchResult(
                movie_id=row.id,
                display_title=row.display_title,
                year=row.year,
                score=1.0,
            )
            for row in rows
        }
        return tuple(by_id[movie_id] for movie_id in movie_ids if movie_id in by_id)

    async def get_movie_view(self, movie_id: int) -> MovieView | None:
        async with self._database.session() as session:
            movie = await session.scalar(
                select(Movie).where(
                    Movie.id == movie_id,
                    Movie.status == "indexed",
                )
            )
            if movie is None:
                return None

            quality_rows = (
                await session.execute(
                    select(MovieQuality.quality).where(
                        MovieQuality.movie_id == movie.id
                    )
                )
            ).scalars().all()

        qualities = tuple(
            sorted(
                set(quality_rows),
                key=lambda value: (_QUALITY_ORDER.get(value, 9999), value),
            )
        )
        if not qualities:
            return None

        return MovieView(
            movie_id=movie.id,
            archive_channel_id=movie.archive_channel_id,
            poster_message_id=movie.poster_message_id,
            display_title=movie.display_title,
            year=movie.year,
            qualities=qualities,
        )


def _bounded_result_limit(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return _DEFAULT_RESULT_LIMIT
    return max(1, min(_MAX_RESULT_LIMIT, value))


def _bounded_threshold(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return _DEFAULT_SIMILARITY_THRESHOLD
    return max(
        _MIN_SIMILARITY_THRESHOLD,
        min(_MAX_SIMILARITY_THRESHOLD, float(value)),
    )


def _match_category(
    *,
    query: str,
    candidate: str,
    similarity: float,
    threshold: float,
) -> int | None:
    if candidate == query:
        return 0
    if candidate.startswith(query):
        return 1
    if len(query) >= 2 and query in candidate:
        return 2
    if len(query) >= 3 and similarity >= threshold:
        return 3
    return None
