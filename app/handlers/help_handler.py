from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message


async def cmd_help(message: Message) -> None:
    await message.answer(
        "Student lookup\n\n"
        "Send an ID as text or use /find STUDENT_ID.\n"
        "IDs must contain 1 to 32 digits. Keep any leading zeroes.\n\n"
        "The result includes the student's name, email address, and account.\n"
        "This bot only looks up profiles. It cannot send emails."
    )


def create_router() -> Router:
    router = Router(name=__name__)
    router.message.register(cmd_help, Command("help"))
    return router
