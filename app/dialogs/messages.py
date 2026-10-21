from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, Message


async def update_keyboard(message: Message, markup: InlineKeyboardMarkup | None = None) -> None:
    """A repeated callback may already have installed exactly this keyboard."""
    try:
        await message.edit_reply_markup(reply_markup=markup)
    except TelegramBadRequest as error:
        if "message is not modified" not in error.message.lower():
            raise
