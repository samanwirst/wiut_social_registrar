"""Finish accepted chat updates before closing their database and network clients."""

import asyncio
import logging

from aiogram import BaseMiddleware

logger = logging.getLogger(__name__)


class UpdateDrain(BaseMiddleware):
    def __init__(self):
        self.tasks = set()

    async def __call__(self, handler, event, data):
        task = asyncio.current_task()
        self.tasks.add(task)
        try:
            return await handler(event, data)
        finally:
            self.tasks.discard(task)

    async def close(self):
        # Polling has stopped. Let dispatched updates and same-user lock waiters enter.
        while True:
            await asyncio.sleep(0)
            tasks = tuple(self.tasks)
            if not tasks:
                return
            logger.info("Finishing %s active chat updates before shutdown", len(tasks))
            await asyncio.gather(*tasks, return_exceptions=True)
