from __future__ import annotations

import asyncio
import os

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from cinegate.db.models import (
    AppSetting,
    MessageTemplate,
    Movie,
    MovieQuality,
    UserSearchSession,
)
from cinegate.db.session import Database
from cinegate.services.search_sessions import SearchSessionService

DATABASE_URL = os.getenv("CINEGATE_DATABASE_URL")
ARCHIVE_CHANNEL_ID = -1001234567890
USER_ID = 123456789


async def clean_database(database: Database) -> None:
    async with database.session() as session, session.begin():
        await session.execute(delete(UserSearchSession))
        await session.execute(delete(MovieQuality))
        await session.execute(delete(Movie))
        await session.execute(delete(AppSetting))
        await session.execute(delete(MessageTemplate))


@pytest_asyncio.fixture
async def database() -> Database:
    if not DATABASE_URL:
        pytest.skip("CINEGATE_DATABASE_URL is not configured")

    database = Database(DATABASE_URL, pool_size=4, max_overflow=0)
    await clean_database(database)
    try:
        yield database
    finally:
        await clean_database(database)
        await database.dispose()


async def seed_movie(database: Database, message_id: int, title: str) -> int:
    async with database.session() as session, session.begin():
        movie = Movie(
            archive_channel_id=ARCHIVE_CHANNEL_ID,
            poster_message_id=message_id,
            display_title=title,
            normalized_title=title.casefold(),
            year=2025,
            parser_style="modern",
            status="indexed",
            raw_poster_caption=f"الفيلم: {title}",
            parser_confidence=95,
        )
        session.add(movie)
        await session.flush()
        return movie.id


@pytest.mark.asyncio
async def test_new_session_replaces_old_nonce_and_keeps_latest_state(
    database: Database,
) -> None:
    movie1 = await seed_movie(database, 100, "First")
    movie2 = await seed_movie(database, 200, "Second")
    service = SearchSessionService(database)

    first = await service.replace(
        telegram_user_id=USER_ID,
        raw_query="First",
        normalized_query="first",
        result_movie_ids=(movie1,),
    )
    second = await service.replace(
        telegram_user_id=USER_ID,
        raw_query="Second",
        normalized_query="second",
        result_movie_ids=(movie2,),
    )

    current = await service.get_current(
        telegram_user_id=USER_ID,
        nonce=second.session.nonce,
    )

    assert first.session.nonce != second.session.nonce
    assert current is not None
    assert current.raw_query == "Second"
    assert current.result_movie_ids == (movie2,)


@pytest.mark.asyncio
async def test_two_first_searches_for_same_user_do_not_race_insert(
    database: Database,
) -> None:
    movie1 = await seed_movie(database, 100, "First")
    movie2 = await seed_movie(database, 200, "Second")
    service = SearchSessionService(database)

    first, second = await asyncio.gather(
        service.replace(
            telegram_user_id=USER_ID,
            raw_query="First",
            normalized_query="first",
            result_movie_ids=(movie1,),
        ),
        service.replace(
            telegram_user_id=USER_ID,
            raw_query="Second",
            normalized_query="second",
            result_movie_ids=(movie2,),
        ),
    )

    async with database.session() as session:
        row = await session.scalar(
            select(UserSearchSession).where(
                UserSearchSession.telegram_user_id == USER_ID
            )
        )

    assert row is not None
    assert row.nonce in {first.session.nonce, second.session.nonce}
    assert tuple(row.result_movie_ids) in {(movie1,), (movie2,)}


@pytest.mark.asyncio
async def test_stale_nonce_cannot_claim_movie(database: Database) -> None:
    movie1 = await seed_movie(database, 100, "First")
    movie2 = await seed_movie(database, 200, "Second")
    service = SearchSessionService(database)

    stale = await service.replace(
        telegram_user_id=USER_ID,
        raw_query="First",
        normalized_query="first",
        result_movie_ids=(movie1,),
    )
    current = await service.replace(
        telegram_user_id=USER_ID,
        raw_query="Second",
        normalized_query="second",
        result_movie_ids=(movie2,),
    )

    stale_claim = await service.claim_movie(
        telegram_user_id=USER_ID,
        nonce=stale.session.nonce,
        movie_id=movie1,
    )
    current_claim = await service.claim_movie(
        telegram_user_id=USER_ID,
        nonce=current.session.nonce,
        movie_id=movie2,
    )

    assert stale_claim is None
    assert current_claim is not None
    assert current_claim.state == "opening"


@pytest.mark.asyncio
async def test_movie_must_belong_to_stored_result_ids(database: Database) -> None:
    movie1 = await seed_movie(database, 100, "First")
    movie2 = await seed_movie(database, 200, "Second")
    service = SearchSessionService(database)

    replacement = await service.replace(
        telegram_user_id=USER_ID,
        raw_query="First",
        normalized_query="first",
        result_movie_ids=(movie1,),
    )

    claimed = await service.claim_movie(
        telegram_user_id=USER_ID,
        nonce=replacement.session.nonce,
        movie_id=movie2,
    )

    assert claimed is None


@pytest.mark.asyncio
async def test_rapid_duplicate_movie_claim_has_single_winner(database: Database) -> None:
    movie_id = await seed_movie(database, 100, "First")
    service = SearchSessionService(database)

    replacement = await service.replace(
        telegram_user_id=USER_ID,
        raw_query="First",
        normalized_query="first",
        result_movie_ids=(movie_id,),
    )

    first, second = await asyncio.gather(
        service.claim_movie(
            telegram_user_id=USER_ID,
            nonce=replacement.session.nonce,
            movie_id=movie_id,
        ),
        service.claim_movie(
            telegram_user_id=USER_ID,
            nonce=replacement.session.nonce,
            movie_id=movie_id,
        ),
    )

    assert sum(item is not None for item in (first, second)) == 1


@pytest.mark.asyncio
async def test_failed_copy_can_reset_opening_state(database: Database) -> None:
    movie_id = await seed_movie(database, 100, "First")
    service = SearchSessionService(database)

    replacement = await service.replace(
        telegram_user_id=USER_ID,
        raw_query="First",
        normalized_query="first",
        result_movie_ids=(movie_id,),
    )
    claim = await service.claim_movie(
        telegram_user_id=USER_ID,
        nonce=replacement.session.nonce,
        movie_id=movie_id,
    )
    assert claim is not None

    reset = await service.reset_opening(
        telegram_user_id=USER_ID,
        nonce=replacement.session.nonce,
        movie_id=movie_id,
    )
    current = await service.get_current(
        telegram_user_id=USER_ID,
        nonce=replacement.session.nonce,
    )

    assert reset
    assert current is not None
    assert current.state == "results"
    assert current.selected_movie_id is None


@pytest.mark.asyncio
async def test_back_transition_has_single_winner(database: Database) -> None:
    movie_id = await seed_movie(database, 100, "First")
    service = SearchSessionService(database)

    replacement = await service.replace(
        telegram_user_id=USER_ID,
        raw_query="First",
        normalized_query="first",
        result_movie_ids=(movie_id,),
    )
    claim = await service.claim_movie(
        telegram_user_id=USER_ID,
        nonce=replacement.session.nonce,
        movie_id=movie_id,
    )
    assert claim is not None

    completed = await service.complete_movie(
        telegram_user_id=USER_ID,
        nonce=replacement.session.nonce,
        movie_id=movie_id,
        poster_message_id=500,
    )
    assert completed

    first, second = await asyncio.gather(
        service.claim_back(
            telegram_user_id=USER_ID,
            nonce=replacement.session.nonce,
        ),
        service.claim_back(
            telegram_user_id=USER_ID,
            nonce=replacement.session.nonce,
        ),
    )

    assert sum(item is not None for item in (first, second)) == 1


@pytest.mark.asyncio
async def test_stale_result_message_cannot_overwrite_new_search(database: Database) -> None:
    movie1 = await seed_movie(database, 100, "First")
    movie2 = await seed_movie(database, 200, "Second")
    service = SearchSessionService(database)

    old = await service.replace(
        telegram_user_id=USER_ID,
        raw_query="First",
        normalized_query="first",
        result_movie_ids=(movie1,),
    )
    new = await service.replace(
        telegram_user_id=USER_ID,
        raw_query="Second",
        normalized_query="second",
        result_movie_ids=(movie2,),
    )

    stale_write = await service.set_result_message(
        telegram_user_id=USER_ID,
        nonce=old.session.nonce,
        message_id=700,
    )
    current_write = await service.set_result_message(
        telegram_user_id=USER_ID,
        nonce=new.session.nonce,
        message_id=701,
    )

    assert not stale_write
    assert current_write

    current = await service.get_current(
        telegram_user_id=USER_ID,
        nonce=new.session.nonce,
    )
    assert current is not None
    assert current.result_message_id == 701
