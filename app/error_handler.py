"""Safe transport errors without logging updates, credentials, or request URLs."""

import logging

from aiogram.exceptions import TelegramAPIError
from aiogram.types import ErrorEvent

logger = logging.getLogger(__name__)


async def handle_error(event: ErrorEvent, runtime_health=None) -> bool:
    logger.error("Update failed (%s).", type(event.exception).__name__)
    if runtime_health is not None:
        runtime_health.incident("handler", event.exception)
    try:
        if event.update.message:
            await event.update.message.answer("Something went wrong. Please try again later")
        elif event.update.callback_query:
            await event.update.callback_query.answer(
                "Something went wrong. Please try again later", show_alert=True
            )
    except TelegramAPIError:
        logger.warning("Could not send the error response.")
    return True
