"""Run retention regardless of whether the organizer HTTP server is enabled."""

import asyncio
import logging
from contextlib import suppress

from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)


class AnswerCleanup:
    def __init__(self, repository, *, interval: float = 600):
        self.repository = repository
        self.interval = interval
        self.task: asyncio.Task | None = None

    async def start(self) -> None:
        if self.task is not None:
            raise RuntimeError("Answer expiration is already running.")
        await self.repository.purge_answers()
        self.task = asyncio.create_task(self._run(), name="expire-event-answers")

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self.interval)
            try:
                await self.repository.purge_answers()
            except SQLAlchemyError as error:
                logger.error("Answer expiration failed (%s); will retry.", type(error).__name__)

    async def close(self) -> None:
        if self.task is not None:
            task, self.task = self.task, None
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
