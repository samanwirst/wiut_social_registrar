"""Registration prompts shared by commands, text input, and contact handling."""

import logging

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

from app.education import EDUCATION_LEVELS
from registrar.errors import GraphError

logger = logging.getLogger(__name__)


async def phone_prompt(message: Message, text: str | None = None) -> None:
    await message.answer(
        text
        or "Your email is verified. Next, tap Share phone number below "
        "to share your own Telegram contact. Your number will be saved with your profile.\n"
        "Use /cancel to change your student ID.",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="Share phone number", request_contact=True)]],
            resize_keyboard=True,
            one_time_keyboard=True,
        ),
    )


async def education_prompt(message: Message) -> None:
    buttons = [
        InlineKeyboardButton(text=label, callback_data=f"education:{key}")
        for key, label in EDUCATION_LEVELS.items()
    ]
    await message.answer(
        "Select your current education level to finish registration:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[buttons[:2], buttons[2:]]),
    )


async def code_prompt(message, status):
    text = (
        "Check the Outlook mailbox linked to your student ID and enter the 6-digit code here. "
        "The code expires in 10 minutes.\nUse /resend for a new code or /cancel to change your ID."
    )
    if status == "unknown":
        text = (
            "Microsoft did not confirm submission. If the verification email arrives in Outlook, "
            "enter its 6-digit code here. Otherwise, wait 60 seconds and use /resend."
        )
    await message.answer(text)


async def request_code(message, service, student_id):
    try:
        status = await service.request_code(message.from_user.id, student_id)
    except ValueError as error:
        await message.answer(str(error))
        return
    except GraphError as error:
        logger.warning("Registration email unavailable (%s).", type(error).__name__)
        await message.answer("Registration is temporarily unavailable. Please try again later.")
        return
    await code_prompt(message, status)


async def prompt_remaining_profile_fields(message: Message, repository) -> bool:
    field = await repository.next_profile_field(message.from_user.id)
    if field == "education":
        await education_prompt(message)
    elif field == "phone":
        await phone_prompt(message)
    else:
        return False
    return True
