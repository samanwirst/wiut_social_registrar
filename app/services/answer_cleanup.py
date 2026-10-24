"""Run retention regardless of whether the organizer HTTP server is enabled."""

import asyncio
import logging
from contextlib import suppress

logger = logging.getLogger(__name__)


class AnswerCleanup:
    def __init__(self, repository, *, interval: float = 600, health=None):
        self.repository = repository
        self.interval = interval
        self.task: asyncio.Task | None = None
        self.health = health

    async def start(self) -> None:
        if self.task is not None:
            raise RuntimeError("Answer expiration is already running.")
        healthy = await self._purge()
        self.task = asyncio.create_task(self._run(healthy), name="expire-event-answers")

    async def _purge(self):
        try:
            await asyncio.wait_for(self.repository.purge_answers(), timeout=10)
        except Exception as error:
            logger.error("Answer expiration failed (%s); will retry.", type(error).__name__)
            if self.health:
                self.health.report("cleanup", False, type(error).__name__)
            return False
        if self.health:
            self.health.report("cleanup", True)
        return True

    async def _run(self, healthy) -> None:
        while True:
            await asyncio.sleep(self.interval if healthy else min(30, self.interval))
            healthy = await self._purge()

    async def close(self) -> None:
        if self.task is not None:
            task, self.task = self.task, None
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
