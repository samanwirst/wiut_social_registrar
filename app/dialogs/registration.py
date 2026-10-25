"""Registration prompts shared by commands, text input, and contact handling."""

import logging

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from aiogram.utils.formatting import Bold, Code, Text

from app.chat_formatting import card, error_text
from app.education import EDUCATION_LEVELS
from registrar.errors import GraphError

logger = logging.getLogger(__name__)


async def phone_prompt(message: Message, text: str | None = None) -> None:
    await message.answer(
        **card(
            "Step 3 of 4",
            text
            or Text(
                "Your email is verified\n",
                "Tap ",
                Bold("Share phone number"),
                " below to share your own Telegram contact\n\n",
                "Your number will be saved with your student profile",
            ),
        ).as_kwargs(),
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
        **card(
            "Step 4 of 4",
            "Select your current education level to finish registration",
        ).as_kwargs(),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[buttons[:2], buttons[2:]]),
    )


async def code_prompt(message, status):
    text = (
        "Microsoft accepted your verification email\n"
        "Open the Outlook mailbox linked to your student ID and enter the 6-digit code here\n"
        "The code expires in 10 minutes\n\n"
        "/resend — request a new code"
    )
    if status == "failed":
        text = (
            "We couldn't send your verification email\n\n"
            "Please wait 60 seconds and use /resend to try again"
        )
    elif status != "accepted":
        text = (
            "Microsoft did not confirm email submission\n"
            "We can't confirm that a code was sent\n"
            "If a code arrives, you can enter it here\n\n"
            "Otherwise, wait 60 seconds and use /resend"
        )
    await message.answer(**card("Step 2 of 4", text).as_kwargs())


async def welcome(message: Message) -> None:
    content = Text(
        Bold("Welcome to Social Registrar"),
        "\n",
        "Register once for WIUT events, advisor applications, and more\n\n",
        Bold("Step 1 of 4"),
        "\n",
        "Send your own student ID as text, including any leading zeroes\n",
        "For example: ",
        Code("00000001"),
    )
    await message.answer(**content.as_kwargs(), reply_markup=ReplyKeyboardRemove())


async def request_code(message, service, student_id):
    try:
        status = await service.request_code(message.from_user.id, student_id)
    except ValueError as error:
        await message.answer(error_text(error))
        return
    except GraphError as error:
        logger.warning("Registration email unavailable (%s).", type(error).__name__)
        await message.answer(
            "Registration is temporarily unavailable\nWe couldn't send a verification email — please try again later"
        )
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
