from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramAPIError
from aiogram.types import ErrorEvent

from app.handlers import create_routers
from app.services.registrar_service import RegistrarService
from config import BotSettings
from registrar.config import ConfigurationError

logger = logging.getLogger(__name__)


class BotApp:
    def __init__(self, settings: BotSettings):
        self.bot = Bot(token=settings.token)
        self.dp = Dispatcher()
        self.registrar_service = RegistrarService(settings.graph)
        self.dp.include_routers(*create_routers())
        self.dp.message.middleware(self.inject_dependencies)
        self.dp.errors.register(self.handle_error)

    async def inject_dependencies(self, handler, event, data):
        data["registrar_service"] = self.registrar_service
        return await handler(event, data)

    async def handle_error(self, event: ErrorEvent) -> bool:
        # Log exception classes, never update payloads or token-bearing URLs.
        logger.error("Update failed (%s).", type(event.exception).__name__)
        if event.update.message:
            try:
                await event.update.message.answer("Something went wrong. Please try again later.")
            except TelegramAPIError:
                logger.warning("Could not send the error response.")
        return True

    async def check_connection(self):
        me = await self.bot.get_me()
        await self.registrar_service.check_connection()
        return me

    async def run(self) -> None:
        webhook = await self.bot.get_webhook_info()
        if webhook.url:
            raise ConfigurationError("A Telegram webhook is configured. Remove it before starting long polling.")
        logger.info("Starting polling...")
        await self.dp.start_polling(
            self.bot, allowed_updates=self.dp.resolve_used_update_types(),
            tasks_concurrency_limit=16, close_bot_session=False,
        )

    async def shutdown(self) -> None:
        try:
            await self.registrar_service.close()
        finally:
            await self.dp.storage.close()
            await self.bot.session.close()
