from __future__ import annotations

from dataclasses import dataclass

from aiogram import Bot, Dispatcher

from cinegate.bot.archive_router import build_archive_router
from cinegate.bot.user_router import build_user_router
from cinegate.config import SecretsSettings, get_settings
from cinegate.db.session import Database
from cinegate.services.archive_indexer import ArchiveIndexService
from cinegate.services.movie_search import MovieSearchService
from cinegate.services.owner_notifier import OwnerArchiveNotifier
from cinegate.services.search_sessions import SearchSessionService


@dataclass(slots=True)
class AppRuntime:
    settings: SecretsSettings
    database: Database
    bot: Bot
    dispatcher: Dispatcher

    async def close(self) -> None:
        try:
            await self.bot.session.close()
        finally:
            await self.database.dispose()


def build_runtime(settings: SecretsSettings | None = None) -> AppRuntime:
    settings = settings or get_settings()
    database = Database(settings.database_url.get_secret_value())
    bot = Bot(token=settings.bot_token.get_secret_value())

    indexer = ArchiveIndexService(database)
    notifier = OwnerArchiveNotifier(database, bot)
    search = MovieSearchService(database)
    search_sessions = SearchSessionService(database)

    dispatcher = Dispatcher()
    dispatcher.include_router(build_archive_router(indexer, notifier))
    dispatcher.include_router(
        build_user_router(
            database=database,
            search=search,
            sessions=search_sessions,
        )
    )

    return AppRuntime(
        settings=settings,
        database=database,
        bot=bot,
        dispatcher=dispatcher,
    )
