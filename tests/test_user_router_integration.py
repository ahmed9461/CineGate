from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError

from cinegate.bot.callbacks import (
    MovieBackCallback,
    MovieSelectCallback,
    QualitySelectCallback,
)
from cinegate.bot.user_router import build_user_router
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
from cinegate.services.movie_search import MovieSearchService
from cinegate.services.rate_limit import AbuseProtection, SlidingWindowLimiter
from cinegate.services.reward_sessions import RewardSessionService
from cinegate.services.search_sessions import SearchSessionService

DATABASE_URL = os.getenv("CINEGATE_DATABASE_URL")
ARCHIVE_CHANNEL_ID = -1001234567890
USER_ID = 123456789


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


async def seed_movie(database: Database) -> int:
    async with database.session() as session, session.begin():
        movie = Movie(
            archive_channel_id=ARCHIVE_CHANNEL_ID,
            poster_message_id=100,
            display_title="Interstellar",
            normalized_title="interstellar",
            year=2014,
            parser_style="modern",
            status="indexed",
            raw_poster_caption="الفيلم: Interstellar",
            parser_confidence=95,
        )
        session.add(movie)
        await session.flush()

        for message_id, quality in ((101, "720p"), (102, "1080p")):
            session.add(
                MovieQuality(
                    movie_id=movie.id,
                    archive_channel_id=ARCHIVE_CHANNEL_ID,
                    archive_message_id=message_id,
                    quality=quality,
                    raw_caption=f"Interstellar 2014 #{quality}",
                    extracted_title="Interstellar",
                    normalized_title="interstellar",
                    extracted_year=2014,
                    parser_confidence=95,
                )
            )
        await session.flush()
        return movie.id


class FakeIncomingMessage:
    def __init__(self, text: str, *, message_id: int = 10) -> None:
        self.text = text
        self.message_id = message_id
        self.from_user = SimpleNamespace(id=USER_ID)
        self.chat = SimpleNamespace(id=USER_ID)
        self.answers: list[SimpleNamespace] = []
        self._next_answer_id = 1000

    async def answer(self, text: str, reply_markup=None):
        sent = SimpleNamespace(
            message_id=self._next_answer_id,
            text=text,
            reply_markup=reply_markup,
        )
        self._next_answer_id += 1
        self.answers.append(sent)
        return sent


class FakeCallback:
    def __init__(self) -> None:
        self.from_user = SimpleNamespace(id=USER_ID)
        self.answers: list[tuple[str | None, bool]] = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))


class FakeBot:
    def __init__(self) -> None:
        self.copied: list[dict] = []
        self.sent: list[SimpleNamespace] = []
        self.deleted: list[tuple[int, int]] = []
        self._next_message_id = 2000

    async def copy_message(self, **kwargs):
        self.copied.append(kwargs)
        result = SimpleNamespace(message_id=self._next_message_id)
        self._next_message_id += 1
        return result

    async def send_message(self, chat_id: int, text: str, reply_markup=None):
        sent = SimpleNamespace(
            message_id=self._next_message_id,
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
        )
        self._next_message_id += 1
        self.sent.append(sent)
        return sent

    async def delete_message(self, *, chat_id: int, message_id: int):
        self.deleted.append((chat_id, message_id))


def handler(router, observer_name: str, callback_name: str):
    observer = getattr(router, observer_name)
    return next(
        item.callback
        for item in observer.handlers
        if item.callback.__name__ == callback_name
    )


@pytest.mark.asyncio
async def test_direct_search_movie_open_and_back_flow(database: Database) -> None:
    movie_id = await seed_movie(database)
    search = MovieSearchService(database)
    sessions = SearchSessionService(database)
    router = build_user_router(
        database=database,
        search=search,
        sessions=sessions,
        rewards=RewardSessionService(database),
    )
    bot = FakeBot()

    search_handler = handler(router, "message", "direct_movie_search")
    incoming = FakeIncomingMessage("Interstllar")
    await search_handler(incoming, bot=bot)

    assert len(incoming.answers) == 1
    results_message = incoming.answers[0]
    assert "وجدنا 1 نتائج بحث" in results_message.text
    assert results_message.reply_markup is not None

    movie_button = results_message.reply_markup.inline_keyboard[0][0]
    assert movie_button.callback_data is not None
    movie_callback_data = MovieSelectCallback.unpack(movie_button.callback_data)
    assert movie_callback_data.movie_id == movie_id

    select_handler = handler(router, "callback_query", "select_movie")
    select_callback = FakeCallback()
    await select_handler(
        select_callback,
        callback_data=movie_callback_data,
        bot=bot,
    )

    assert len(bot.copied) == 1
    copy_call = bot.copied[0]
    assert copy_call["from_chat_id"] == ARCHIVE_CHANNEL_ID
    assert copy_call["message_id"] == 100
    assert [button.text for button in copy_call["reply_markup"].inline_keyboard[0]] == [
        "720p",
        "1080p",
    ]
    assert (USER_ID, results_message.message_id) in bot.deleted

    back_button = copy_call["reply_markup"].inline_keyboard[-1][0]
    assert back_button.callback_data is not None
    back_data = MovieBackCallback.unpack(back_button.callback_data)

    back_handler = handler(router, "callback_query", "back_to_results")
    back_callback = FakeCallback()
    await back_handler(
        back_callback,
        callback_data=back_data,
        bot=bot,
    )

    assert len(bot.sent) == 1
    assert "وجدنا 1 نتائج بحث" in bot.sent[0].text
    assert (USER_ID, 2000) in bot.deleted

    async with database.session() as session:
        state = await session.scalar(
            select(UserSearchSession).where(
                UserSearchSession.telegram_user_id == USER_ID
            )
        )

    assert state is not None
    assert state.state == "results"
    assert state.poster_message_id is None


@pytest.mark.asyncio
async def test_no_result_uses_default_message_without_keyboard(
    database: Database,
) -> None:
    router = build_user_router(
        database=database,
        search=MovieSearchService(database),
        sessions=SearchSessionService(database),
        rewards=RewardSessionService(database),
    )
    bot = FakeBot()
    search_handler = handler(router, "message", "direct_movie_search")

    incoming = FakeIncomingMessage("DefinitelyNotInCatalog")
    await search_handler(incoming, bot=bot)

    assert len(incoming.answers) == 1
    assert "عذرا لم أجد نتائج بحث" in incoming.answers[0].text
    assert incoming.answers[0].reply_markup is None


@pytest.mark.asyncio
async def test_slash_command_is_not_treated_as_movie_search(database: Database) -> None:
    router = build_user_router(
        database=database,
        search=MovieSearchService(database),
        sessions=SearchSessionService(database),
        rewards=RewardSessionService(database),
    )
    bot = FakeBot()
    search_handler = handler(router, "message", "direct_movie_search")

    incoming = FakeIncomingMessage("/help")
    await search_handler(incoming, bot=bot)

    assert incoming.answers == []

    async with database.session() as session:
        state = await session.scalar(
            select(UserSearchSession).where(
                UserSearchSession.telegram_user_id == USER_ID
            )
        )
    assert state is None



@pytest.mark.asyncio
async def test_rapid_duplicate_movie_callback_copies_poster_once(
    database: Database,
) -> None:
    await seed_movie(database)
    search = MovieSearchService(database)
    sessions = SearchSessionService(database)
    router = build_user_router(
        database=database,
        search=search,
        sessions=sessions,
        rewards=RewardSessionService(database),
    )
    bot = FakeBot()

    search_handler = handler(router, "message", "direct_movie_search")
    incoming = FakeIncomingMessage("Interstellar")
    await search_handler(incoming, bot=bot)

    button = incoming.answers[0].reply_markup.inline_keyboard[0][0]
    assert button.callback_data is not None
    callback_data = MovieSelectCallback.unpack(button.callback_data)

    select_handler = handler(router, "callback_query", "select_movie")
    first_callback = FakeCallback()
    second_callback = FakeCallback()

    await asyncio.gather(
        select_handler(
            first_callback,
            callback_data=callback_data,
            bot=bot,
        ),
        select_handler(
            second_callback,
            callback_data=callback_data,
            bot=bot,
        ),
    )

    assert len(bot.copied) == 1


@pytest.mark.asyncio
async def test_no_result_message_can_be_changed_from_database(
    database: Database,
) -> None:
    custom_text = "الفيلم غير موجود حاليًا."
    async with database.session() as session, session.begin():
        session.add(
            MessageTemplate(
                key="search_no_results",
                body=custom_text,
            )
        )

    router = build_user_router(
        database=database,
        search=MovieSearchService(database),
        sessions=SearchSessionService(database),
        rewards=RewardSessionService(database),
    )
    bot = FakeBot()
    search_handler = handler(router, "message", "direct_movie_search")

    incoming = FakeIncomingMessage("NotAvailable")
    await search_handler(incoming, bot=bot)

    assert incoming.answers[0].text == custom_text



@pytest.mark.asyncio
async def test_result_message_is_deleted_if_session_persistence_fails(
    database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await seed_movie(database)
    search = MovieSearchService(database)
    sessions = SearchSessionService(database)
    router = build_user_router(
        database=database,
        search=search,
        sessions=sessions,
        rewards=RewardSessionService(database),
    )
    bot = FakeBot()

    async def fail_set_result_message(**kwargs):
        raise SQLAlchemyError("simulated persistence failure")

    monkeypatch.setattr(
        sessions,
        "set_result_message",
        fail_set_result_message,
    )

    search_handler = handler(router, "message", "direct_movie_search")
    incoming = FakeIncomingMessage("Interstellar")

    with pytest.raises(SQLAlchemyError):
        await search_handler(incoming, bot=bot)

    assert len(incoming.answers) == 1
    assert (USER_ID, incoming.answers[0].message_id) in bot.deleted


@pytest.mark.asyncio
async def test_copied_poster_is_deleted_if_movie_state_persistence_fails(
    database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await seed_movie(database)
    search = MovieSearchService(database)
    sessions = SearchSessionService(database)
    router = build_user_router(
        database=database,
        search=search,
        sessions=sessions,
        rewards=RewardSessionService(database),
    )
    bot = FakeBot()

    search_handler = handler(router, "message", "direct_movie_search")
    incoming = FakeIncomingMessage("Interstellar")
    await search_handler(incoming, bot=bot)

    button = incoming.answers[0].reply_markup.inline_keyboard[0][0]
    assert button.callback_data is not None
    callback_data = MovieSelectCallback.unpack(button.callback_data)

    async def fail_complete_movie(**kwargs):
        raise SQLAlchemyError("simulated persistence failure")

    monkeypatch.setattr(sessions, "complete_movie", fail_complete_movie)

    select_handler = handler(router, "callback_query", "select_movie")

    with pytest.raises(SQLAlchemyError):
        await select_handler(
            FakeCallback(),
            callback_data=callback_data,
            bot=bot,
        )

    assert len(bot.copied) == 1
    assert (USER_ID, 2000) in bot.deleted



async def configure_reward_ui(database: Database) -> None:
    async with database.session() as session, session.begin():
        session.add_all(
            [
                AppSetting(
                    key="public_base_url",
                    value="https://cinegate.example",
                ),
                AppSetting(
                    key="adsgram_block_id",
                    value="12345",
                ),
            ]
        )


async def open_movie_for_quality_test(database: Database, bot: FakeBot):
    search = MovieSearchService(database)
    sessions = SearchSessionService(database)
    rewards = RewardSessionService(database)
    router = build_user_router(
        database=database,
        search=search,
        sessions=sessions,
        rewards=rewards,
    )

    search_handler = handler(router, "message", "direct_movie_search")
    incoming = FakeIncomingMessage("Interstellar")
    await search_handler(incoming, bot=bot)

    movie_button = incoming.answers[0].reply_markup.inline_keyboard[0][0]
    movie_data = MovieSelectCallback.unpack(movie_button.callback_data)
    select_handler = handler(router, "callback_query", "select_movie")
    await select_handler(
        FakeCallback(),
        callback_data=movie_data,
        bot=bot,
    )

    return router, bot.copied[0]["reply_markup"]


@pytest.mark.asyncio
async def test_rapid_duplicate_quality_click_sends_one_reward_prompt(
    database: Database,
) -> None:
    await seed_movie(database)
    await configure_reward_ui(database)
    bot = FakeBot()
    router, keyboard = await open_movie_for_quality_test(database, bot)

    quality_button = keyboard.inline_keyboard[0][0]
    assert quality_button.callback_data is not None
    quality_data = QualitySelectCallback.unpack(quality_button.callback_data)
    quality_handler = handler(router, "callback_query", "select_quality")

    first_callback = FakeCallback()
    second_callback = FakeCallback()
    await asyncio.gather(
        quality_handler(
            first_callback,
            callback_data=quality_data,
            bot=bot,
        ),
        quality_handler(
            second_callback,
            callback_data=quality_data,
            bot=bot,
        ),
    )

    assert len(bot.sent) == 1
    reward_message = bot.sent[0]
    assert "Interstellar" in reward_message.text
    assert "720p" in reward_message.text
    button = reward_message.reply_markup.inline_keyboard[0][0]
    assert button.web_app is not None
    assert button.web_app.url.startswith(
        "https://cinegate.example/miniapp/reward/"
    )

    async with database.session() as session:
        rewards = (
            await session.execute(select(RewardSession))
        ).scalars().all()

    assert len(rewards) == 1
    assert rewards[0].prompt_message_id == reward_message.message_id


@pytest.mark.asyncio
async def test_active_reward_prevents_switching_quality_silently(
    database: Database,
) -> None:
    await seed_movie(database)
    await configure_reward_ui(database)
    bot = FakeBot()
    router, keyboard = await open_movie_for_quality_test(database, bot)
    quality_handler = handler(router, "callback_query", "select_quality")

    first_button = keyboard.inline_keyboard[0][0]
    second_button = keyboard.inline_keyboard[0][1]
    first_data = QualitySelectCallback.unpack(first_button.callback_data)
    second_data = QualitySelectCallback.unpack(second_button.callback_data)

    await quality_handler(
        FakeCallback(),
        callback_data=first_data,
        bot=bot,
    )

    conflict_callback = FakeCallback()
    await quality_handler(
        conflict_callback,
        callback_data=second_data,
        bot=bot,
    )

    assert len(bot.sent) == 1
    assert conflict_callback.answers
    text, show_alert = conflict_callback.answers[-1]
    assert show_alert is True
    assert "720p" in (text or "")



def strict_abuse_protection() -> AbuseProtection:
    return AbuseProtection(
        search=SlidingWindowLimiter(
            limit=1,
            window_seconds=60,
            max_keys=100,
        ),
        callback=SlidingWindowLimiter(
            limit=1,
            window_seconds=60,
            max_keys=100,
        ),
        reward_claim=SlidingWindowLimiter(
            limit=1,
            window_seconds=60,
            max_keys=100,
        ),
    )


@pytest.mark.asyncio
async def test_rapid_search_is_rate_limited_before_second_search(
    database: Database,
) -> None:
    await seed_movie(database)
    abuse = strict_abuse_protection()
    router = build_user_router(
        database=database,
        search=MovieSearchService(database),
        sessions=SearchSessionService(database),
        rewards=RewardSessionService(database),
        abuse=abuse,
    )
    bot = FakeBot()
    search_handler = handler(router, "message", "direct_movie_search")

    first = FakeIncomingMessage("Interstellar")
    second = FakeIncomingMessage("Interstellar")

    await search_handler(first, bot=bot)
    await search_handler(second, bot=bot)

    assert "وجدنا 1 نتائج بحث" in first.answers[0].text
    assert len(second.answers) == 1
    assert "طلباتك سريعة جدًا" in second.answers[0].text


@pytest.mark.asyncio
async def test_rapid_user_callback_is_rate_limited_before_state_machine(
    database: Database,
) -> None:
    movie_id = await seed_movie(database)
    abuse = strict_abuse_protection()
    sessions = SearchSessionService(database)
    search = MovieSearchService(database)
    router = build_user_router(
        database=database,
        search=search,
        sessions=sessions,
        rewards=RewardSessionService(database),
        abuse=abuse,
    )
    bot = FakeBot()

    incoming = FakeIncomingMessage("Interstellar")
    await handler(router, "message", "direct_movie_search")(incoming, bot=bot)
    button = incoming.answers[0].reply_markup.inline_keyboard[0][0]
    callback_data = MovieSelectCallback.unpack(button.callback_data)
    assert callback_data.movie_id == movie_id

    callback_handler = handler(router, "callback_query", "select_movie")
    first = FakeCallback()
    second = FakeCallback()

    await callback_handler(first, callback_data=callback_data, bot=bot)
    await callback_handler(second, callback_data=callback_data, bot=bot)

    assert len(bot.copied) == 1
    assert second.answers
    assert "طلباتك سريعة جدًا" in (second.answers[-1][0] or "")



@pytest.mark.asyncio
async def test_repeated_blocked_searches_emit_one_cooldown_notice(
    database: Database,
) -> None:
    await seed_movie(database)
    abuse = strict_abuse_protection()
    abuse.notice = SlidingWindowLimiter(
        limit=1,
        window_seconds=60,
        max_keys=100,
    )
    router = build_user_router(
        database=database,
        search=MovieSearchService(database),
        sessions=SearchSessionService(database),
        rewards=RewardSessionService(database),
        abuse=abuse,
    )
    bot = FakeBot()
    search_handler = handler(router, "message", "direct_movie_search")

    allowed = FakeIncomingMessage("Interstellar")
    blocked_one = FakeIncomingMessage("Interstellar")
    blocked_two = FakeIncomingMessage("Interstellar")
    blocked_three = FakeIncomingMessage("Interstellar")

    await search_handler(allowed, bot=bot)
    await search_handler(blocked_one, bot=bot)
    await search_handler(blocked_two, bot=bot)
    await search_handler(blocked_three, bot=bot)

    assert len(blocked_one.answers) == 1
    assert "طلباتك سريعة جدًا" in blocked_one.answers[0].text
    assert blocked_two.answers == []
    assert blocked_three.answers == []
