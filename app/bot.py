from __future__ import annotations

import logging
from contextlib import AsyncExitStack

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import PRODUCTION, TEST
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.storage.memory import SimpleEventIsolation

from app.commands import CommandMenu
from app.configuration.database import local_database_url
from app.db import Database
from app.error_handler import handle_error
from app.event_repository import EventRepository
from app.handlers import create_routers
from app.middleware import CommandMenuMiddleware, PrivateChatMiddleware, UserContextMiddleware
from app.miniapp import MiniAppServer
from app.repositories import RegistrationRepository
from app.services.answer_cleanup import AnswerCleanup
from app.services.registrar_service import RegistrarService
from app.services.registration_service import RegistrationService
from app.services.update_drain import UpdateDrain
from app.surveys import EventSurvey
from config import BotSettings
from registrar.config import ConfigurationError

logger = logging.getLogger(__name__)


class BotApp:
    def __init__(self, settings: BotSettings):
        self.bot = Bot(
            token=settings.token,
            session=AiohttpSession(api=TEST if settings.telegram_test_environment else PRODUCTION),
        )
        self.command_menu = CommandMenu()
        self.registrar_service = RegistrarService(settings.graph)
        url = settings.database_url or local_database_url(
            settings.graph.env_file, telegram_test=settings.telegram_test_environment
        )
        self.database = Database(url)
        self.event_repository = EventRepository(self.database)
        self.event_survey = EventSurvey(self.event_repository)
        self.miniapp_server = MiniAppServer(self.event_repository, self.bot, settings)
        self.answer_cleanup = AnswerCleanup(self.event_repository)
        self.registration_repository = RegistrationRepository(
            self.database, settings.verification_secret
        )
        self.registration_service = RegistrationService(
            self.registration_repository, self.registrar_service
        )
        self.update_drain = UpdateDrain()
        self.dp = Dispatcher(
            events_isolation=SimpleEventIsolation(),
            registrar_service=self.registrar_service,
            registration_repository=self.registration_repository,
            registration_service=self.registration_service,
            event_repository=self.event_repository,
            event_survey=self.event_survey,
            mini_app_url=settings.mini_app_url,
            command_menu=self.command_menu,
        )
        self.dp.include_routers(*create_routers())
        self.dp.update.outer_middleware(self.update_drain)
        for observer in (self.dp.message, self.dp.callback_query):
            observer.middleware(PrivateChatMiddleware())
            observer.middleware(UserContextMiddleware())
            observer.middleware(CommandMenuMiddleware())
        self.dp.errors.register(handle_error)

    async def check_connection(self):
        await self.database.migrate()
        me = await self.bot.get_me()
        await self.registrar_service.check_connection()
        return me

    async def run(self) -> None:
        webhook = await self.bot.get_webhook_info()
        if webhook.url:
            raise ConfigurationError(
                "A Telegram webhook is configured. Remove it before starting long polling."
            )
        logger.info("Starting polling...")
        try:
            await self.command_menu.install_defaults(self.bot)
        except TelegramAPIError as error:
            logger.warning("Could not initialize the command menu (%s).", type(error).__name__)
        await self.answer_cleanup.start()
        await self.miniapp_server.start()
        await self.dp.start_polling(
            self.bot,
            allowed_updates=self.dp.resolve_used_update_types(),
            tasks_concurrency_limit=16,
            close_bot_session=False,
        )

    async def shutdown(self) -> None:
        async with AsyncExitStack() as resources:
            resources.push_async_callback(self.bot.session.close)
            resources.push_async_callback(self.dp.storage.close)
            resources.push_async_callback(self.database.close)
            resources.push_async_callback(self.registrar_service.close)
            resources.push_async_callback(self.answer_cleanup.close)
            resources.push_async_callback(self.miniapp_server.close)
            resources.push_async_callback(self.update_drain.close)
