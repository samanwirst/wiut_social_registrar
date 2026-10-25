"""One bounded, free-tier Telegram delivery worker with durable, explicit outcomes."""

import asyncio
import logging
import time

from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)

logger = logging.getLogger(__name__)


class BroadcastWorker:
    def __init__(self, repository, bot, *, health=None, interval=0.1, clock=time.monotonic):
        self.repository, self.bot, self.health = repository, bot, health
        self.interval, self.clock = interval, clock
        self.task = None
        self.last_chat = {}

    async def start(self):
        if self.task is not None:
            raise RuntimeError("Broadcast worker is already running")
        self.task = asyncio.create_task(self.run(), name="telegram-broadcasts")

    async def deliver(self, claim):
        target = claim["telegram_id"]
        delay = self.last_chat.get(target, float("-inf")) + 1.1 - self.clock()
        # Bound process memory even if a long-lived bot contacts many students.
        self.last_chat = {
            key: stamp for key, stamp in self.last_chat.items() if self.clock() - stamp < 2
        }
        submitted = False
        try:
            if delay > 0:
                await asyncio.sleep(delay)
            submitted = True
            result = await self.bot.copy_message(
                chat_id=target,
                from_chat_id=claim["owner_id"],
                message_id=claim["source_message_id"],
                allow_paid_broadcast=False,
                request_timeout=15,
            )
        except TelegramRetryAfter as error:
            await self.repository.finish(
                claim, "pending", error_code="rate_limited", retry_after=error.retry_after
            )
            # Telegram's flood wait applies to the bot, not just this recipient.
            await asyncio.sleep(max(1, error.retry_after))
        except TelegramForbiddenError:
            await self.repository.finish(claim, "failed", error_code="blocked")
        except TelegramBadRequest:
            await self.repository.finish(claim, "failed", error_code="rejected")
        except (TelegramNetworkError, TelegramServerError) as error:
            await self.repository.finish(claim, "unknown", error_code="submission_unconfirmed")
            if self.health:
                self.health.incident("broadcast", error)
        except asyncio.CancelledError:
            await asyncio.shield(
                self.repository.finish(
                    claim, "unknown" if submitted else "pending", error_code="interrupted"
                )
            )
            raise
        except TelegramAPIError as error:
            await self.repository.finish(claim, "failed", error_code="telegram_error")
            if self.health:
                self.health.incident("broadcast", error)
        else:
            await self.repository.finish(claim, "sent", message_id=result.message_id)
        finally:
            self.last_chat[target] = self.clock()

    async def run(self):
        maintenance_at = 0
        recovering = True
        while True:
            try:
                if recovering:
                    await self.repository.recover()
                    recovering = False
                if self.clock() >= maintenance_at:
                    await self.repository.maintenance()
                    maintenance_at = self.clock() + 60
                claim = await self.repository.claim()
                if claim is not None:
                    await self.deliver(claim)
                if self.health:
                    self.health.report("broadcasts", True)
                await asyncio.sleep(self.interval if claim else 1)
            except Exception as error:
                logger.error("Broadcast worker failed (%s)", type(error).__name__)
                if self.health:
                    self.health.report("broadcasts", False, type(error).__name__)
                await asyncio.sleep(5)

    async def close(self):
        if self.task is not None:
            task, self.task = self.task, None
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
