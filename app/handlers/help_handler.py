from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message


async def cmd_help(message: Message) -> None:
    await message.answer(
        "Registration\n\n"
        "1. Send your student ID as text. Keep any leading zeroes.\n"
        "2. Open your Outlook mailbox and find the verification email.\n"
        "3. Send the 6-digit code here to verify your email.\n"
        "4. Tap Share phone number to share your own Telegram contact and complete registration.\n\n"
        "Codes expire after 10 minutes and allow 5 incorrect attempts.\n"
        "/resend requests a new code; /cancel changes the pending student ID.\n"
        "After registration, send an ID to look up a profile, or use /start for your own profile."
    )


def create_router() -> Router:
    router = Router(name=__name__)
    router.message.register(cmd_help, Command("help"))
    return router
