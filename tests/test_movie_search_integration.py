from __future__ import annotations

import os

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select, text

from cinegate.db.models import (
    AppSetting,
    Delivery,
    MessageTemplate,
    Movie,
    MovieQuality,
    RewardSession,
    UserSearchSession,
)
from cinegate.db.session import Database
from cinegate.domain.search import SearchQueryError
from cinegate.repositories.settings import SettingsRepository
from cinegate.services.movie_search import MovieSearchService

DATABASE_URL = os.getenv("CINEGATE_DATABASE_URL")
ARCHIVE_CHANNEL_ID = -1001234567890


async def clean_database(database: Database) -> None:
    async with database.session() as session, session.begin():
        await session.execute(delete(Delivery))
        await session.execute(delete(RewardSession))
        await session.execute(delete(UserSearchSession))
        await session.execute(delete(MovieQuality))
        await session.execute(delete(Movie))
        await session.execute(delete(AppSetting))
        await session.execute(delete(MessageTemplate))


@pytest_asyncio.fixture
async def database() -> Database:
    if not DATABASE_URL:
        pytest.skip("CINEGATE_DATABASE_URL is not configured")

    database = Database(DATABASE_URL, pool_size=3, max_overflow=0)
    await clean_database(database)
    try:
        yield database
    finally:
        await clean_database(database)
        await database.dispose()


async def seed_movie(
    database: Database,
    *,
    title: str,
    normalized: str,
    year: int | None,
    status: str = "indexed",
    quality_values: tuple[str, ...] = ("720p",),
) -> int:
    async with database.session() as session, session.begin():
        movie = Movie(
            archive_channel_id=ARCHIVE_CHANNEL_ID,
            poster_message_id=1000 + abs(hash((title, year))) % 1000000,
            display_title=title,
            normalized_title=normalized,
            year=year,
            parser_style="modern",
            status=status,
            raw_poster_caption=f"الفيلم: {title}",
            parser_confidence=95,
        )
        session.add(movie)
        await session.flush()

        for index, quality in enumerate(quality_values, start=1):
            session.add(
                MovieQuality(
                    movie_id=movie.id,
                    archive_channel_id=ARCHIVE_CHANNEL_ID,
                    archive_message_id=movie.poster_message_id + index,
                    quality=quality,
                    raw_caption=f"{title} #{quality}",
                    extracted_title=title,
                    normalized_title=normalized,
                    extracted_year=year,
                    parser_confidence=95,
                )
            )

        await session.flush()
        return movie.id


@pytest.mark.asyncio
async def test_exact_match_ranks_before_near_titles(database: Database) -> None:
    exact_id = await seed_movie(
        database,
        title="Interstellar",
        normalized="interstellar",
        year=2014,
    )
    await seed_movie(
        database,
        title="Interstellar Wars",
        normalized="interstellar wars",
        year=2016,
    )

    results = await MovieSearchService(database).search("Interstellar")

    assert results
    assert results[0].movie_id == exact_id


@pytest.mark.asyncio
async def test_prefix_match_ranks_before_fuzzy(database: Database) -> None:
    prefix_id = await seed_movie(
        database,
        title="Interstellar",
        normalized="interstellar",
        year=2014,
    )
    await seed_movie(
        database,
        title="Winter",
        normalized="winter",
        year=2020,
    )

    results = await MovieSearchService(database).search("Inter")

    assert results
    assert results[0].movie_id == prefix_id


@pytest.mark.asyncio
async def test_typo_query_finds_intended_movie(database: Database) -> None:
    movie_id = await seed_movie(
        database,
        title="Interstellar",
        normalized="interstellar",
        year=2014,
    )
    await seed_movie(
        database,
        title="Inception",
        normalized="inception",
        year=2010,
    )

    results = await MovieSearchService(database).search("Interstllar")

    assert results
    assert results[0].movie_id == movie_id


@pytest.mark.asyncio
async def test_low_similarity_noise_is_excluded(database: Database) -> None:
    await seed_movie(
        database,
        title="Interstellar",
        normalized="interstellar",
        year=2014,
    )

    results = await MovieSearchService(database).search("zzzzzzzz")

    assert results == ()


@pytest.mark.asyncio
async def test_only_indexed_movies_with_qualities_are_returned(database: Database) -> None:
    visible_id = await seed_movie(
        database,
        title="Visible",
        normalized="visible",
        year=2024,
    )
    await seed_movie(
        database,
        title="Visible Draft",
        normalized="visible draft",
        year=2024,
        status="pending",
    )
    await seed_movie(
        database,
        title="Visible Empty",
        normalized="visible empty",
        year=2024,
        quality_values=(),
    )

    results = await MovieSearchService(database).search("Visible")

    assert [result.movie_id for result in results] == [visible_id]


@pytest.mark.asyncio
async def test_result_limit_is_bounded_by_runtime_setting(database: Database) -> None:
    for index in range(8):
        await seed_movie(
            database,
            title=f"Matrix {index}",
            normalized=f"matrix {index}",
            year=2000 + index,
        )

    async with database.session() as session, session.begin():
        await SettingsRepository(session).set("search_result_limit", 2)

    results = await MovieSearchService(database).search("Matrix")

    assert len(results) == 2


@pytest.mark.asyncio
async def test_query_length_is_bounded(database: Database) -> None:
    service = MovieSearchService(database)

    with pytest.raises(SearchQueryError):
        await service.search("x" * 129)


@pytest.mark.asyncio
async def test_hostile_looking_text_is_data_not_sql(database: Database) -> None:
    await seed_movie(
        database,
        title="Safe Movie",
        normalized="safe movie",
        year=2024,
    )
    service = MovieSearchService(database)

    results = await service.search("'; DROP TABLE movies; --")

    assert results == ()

    async with database.session() as session:
        count = await session.scalar(select(func.count(Movie.id)))
    assert count == 1


@pytest.mark.asyncio
async def test_year_named_movie_search_is_preserved(database: Database) -> None:
    movie_id = await seed_movie(
        database,
        title="1917",
        normalized="1917",
        year=2019,
    )

    results = await MovieSearchService(database).search("1917")

    assert results
    assert results[0].movie_id == movie_id


@pytest.mark.asyncio
async def test_movie_view_returns_only_real_qualities_in_stable_order(
    database: Database,
) -> None:
    movie_id = await seed_movie(
        database,
        title="Quality Movie",
        normalized="quality movie",
        year=2025,
        quality_values=("1080p", "480p", "720p"),
    )

    view = await MovieSearchService(database).get_movie_view(movie_id)

    assert view is not None
    assert view.movie_id == movie_id
    assert view.qualities == ("480p", "720p", "1080p")


@pytest.mark.asyncio
async def test_pg_trgm_extension_and_index_are_installed(database: Database) -> None:
    async with database.session() as session:
        extension_exists = await session.scalar(
            text(
                "SELECT EXISTS ("
                "SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'"
                ")"
            )
        )
        canonical_index_exists = await session.scalar(
            text(
                "SELECT to_regclass("
                "'public.ix_movies_normalized_title_trgm'"
                ") IS NOT NULL"
            )
        )
        alias_index_exists = await session.scalar(
            text(
                "SELECT to_regclass("
                "'public.ix_movie_qualities_normalized_title_trgm'"
                ") IS NOT NULL"
            )
        )

    assert extension_exists is True
    assert canonical_index_exists is True
    assert alias_index_exists is True



@pytest.mark.asyncio
async def test_quality_caption_english_title_acts_as_local_search_alias(
    database: Database,
) -> None:
    movie_id = await seed_movie(
        database,
        title="La sociedad de la nieve",
        normalized="la sociedad de la nieve",
        year=2023,
    )

    async with database.session() as session, session.begin():
        quality_row = await session.scalar(
            select(MovieQuality).where(MovieQuality.movie_id == movie_id)
        )
        assert quality_row is not None
        quality_row.extracted_title = "Society of the Snow"
        quality_row.normalized_title = "society of the snow"

    results = await MovieSearchService(database).search("Society of the Snow")

    assert results
    assert results[0].movie_id == movie_id


@pytest.mark.asyncio
async def test_requested_year_prefers_correct_same_title_release(
    database: Database,
) -> None:
    old_id = await seed_movie(
        database,
        title="King Kong",
        normalized="king kong",
        year=1933,
    )
    new_id = await seed_movie(
        database,
        title="King Kong",
        normalized="king kong",
        year=2005,
    )

    results = await MovieSearchService(database).search("King Kong 2005")

    assert results
    assert results[0].movie_id == new_id
    assert any(result.movie_id == old_id for result in results)



@pytest.mark.asyncio
async def test_trigram_knn_queries_are_index_eligible(database: Database) -> None:
    async with database.session() as session, session.begin():
        await session.execute(text("SET LOCAL enable_seqscan = off"))

        canonical_plan_rows = await session.execute(
            text(
                "EXPLAIN (COSTS OFF) "
                "SELECT id FROM movies "
                "ORDER BY normalized_title <-> 'interstellar' "
                "LIMIT 20"
            )
        )
        alias_plan_rows = await session.execute(
            text(
                "EXPLAIN (COSTS OFF) "
                "SELECT id FROM movie_qualities "
                "WHERE normalized_title IS NOT NULL "
                "ORDER BY normalized_title <-> 'interstellar' "
                "LIMIT 20"
            )
        )

    canonical_plan = "\n".join(row[0] for row in canonical_plan_rows)
    alias_plan = "\n".join(row[0] for row in alias_plan_rows)

    assert "ix_movies_normalized_title_trgm" in canonical_plan
    assert "ix_movie_qualities_normalized_title_trgm" in alias_plan
