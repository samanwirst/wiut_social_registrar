from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message


async def cmd_start(message: Message) -> None:
    await message.answer(
        "Send a student ID to look up their name, email address, and account.\n\n"
        "Leading zeroes are preserved. You can also use /find STUDENT_ID.\n"
        "Use /help for instructions."
    )


def create_router() -> Router:
    router = Router(name=__name__)
    router.message.register(cmd_start, CommandStart())
    return router
