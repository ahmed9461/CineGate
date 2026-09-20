from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from aiogram import Bot, Dispatcher

from cinegate.admin.diagnostics import AdminDiagnosticsService
from cinegate.admin.service import OwnerAdminService
from cinegate.bot.archive_router import build_archive_router
from cinegate.bot.owner_router import build_owner_router
from cinegate.bot.user_router import build_user_router
from cinegate.config import SecretsSettings, get_settings
from cinegate.db.session import Database
from cinegate.services.archive_indexer import ArchiveIndexService
from cinegate.services.delivery import DeliveryService
from cinegate.services.movie_search import MovieSearchService
from cinegate.services.owner_notifier import OwnerArchiveNotifier
from cinegate.services.reward_sessions import RewardSessionService
from cinegate.services.search_sessions import SearchSessionService
from cinegate.services.templates import TemplateService
from cinegate.workers.deletion import DeliveryDeletionWorker


@dataclass(slots=True)
class AppRuntime:
    settings: SecretsSettings
    database: Database
    bot: Bot
    dispatcher: Dispatcher
    rewards: RewardSessionService
    delivery: DeliveryService
    deletion_worker: DeliveryDeletionWorker
    stop_event: asyncio.Event = field(default_factory=asyncio.Event)
    worker_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self.worker_task is None:
            self.worker_task = asyncio.create_task(
                self.deletion_worker.run(self.stop_event),
                name="cinegate-delivery-deletion",
            )

    async def close(self) -> None:
        self.stop_event.set()
        if self.worker_task is not None:
            try:
                await self.worker_task
            finally:
                self.worker_task = None

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
    rewards = RewardSessionService(database)
    templates = TemplateService(database)
    owner_admin = OwnerAdminService(database)
    admin_diagnostics = AdminDiagnosticsService(database)
    delivery = DeliveryService(database, bot, templates=templates)
    deletion_worker = DeliveryDeletionWorker(
        delivery_service=delivery,
        bot=bot,
    )

    dispatcher = Dispatcher()
    dispatcher.include_router(build_archive_router(indexer, notifier))
    dispatcher.include_router(
        build_owner_router(
            owner_user_id=settings.owner_user_id,
            admin=owner_admin,
            diagnostics=admin_diagnostics,
            templates=templates,
        )
    )
    dispatcher.include_router(
        build_user_router(
            database=database,
            search=search,
            sessions=search_sessions,
            rewards=rewards,
            templates=templates,
        )
    )

    return AppRuntime(
        settings=settings,
        database=database,
        bot=bot,
        dispatcher=dispatcher,
        rewards=rewards,
        delivery=delivery,
        deletion_worker=deletion_worker,
    )
