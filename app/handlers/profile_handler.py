from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from app.chat_formatting import student_profile


async def cmd_me(message: Message, command: CommandObject, verified_student) -> None:
    if command.args:
        await message.answer("Use /me without arguments to view your own profile")
        return
    if verified_student is None:
        await message.answer("Complete registration first\nSend /start to begin")
        return
    # Middleware loads this profile only from the authenticated Telegram sender's ID.
    await message.answer(**student_profile(verified_student).as_kwargs())


def create_router() -> Router:
    router = Router(name=__name__)
    router.message.register(cmd_me, Command("me"))
    return router
