from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message, ReplyKeyboardRemove

from app.handlers.contact_handler import phone_prompt


async def cmd_start(message: Message, registration_repository, verified_student) -> None:
    await registration_repository.event(message.from_user.id, "bot_started")
    if verified_student:
        await message.answer("Your verified profile:\n\n" + verified_student.format(), parse_mode=None,
                             reply_markup=ReplyKeyboardRemove())
    elif await registration_repository.awaiting_phone(message.from_user.id):
        await phone_prompt(message)
    elif await registration_repository.pending(message.from_user.id):
        await message.answer("Open Outlook and send the 6-digit verification code here.\n"
                             "Use /resend for a new code or /cancel to change your student ID.")
    else:
        await message.answer("Welcome! Send your own student ID to register. Keep any leading zeroes.\n\n"
                             "We will email a 6-digit code to the Outlook mailbox linked to your ID. "
                             "Open Outlook and enter that code here, then share your phone number "
                             "using the Telegram contact button to complete registration.",
                             reply_markup=ReplyKeyboardRemove())


def create_router() -> Router:
    router = Router(name=__name__)
    router.message.register(cmd_start, CommandStart())
    return router
