import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.chat_formatting import error_text
from app.dialogs.registration import (
    code_prompt,
    prompt_remaining_profile_fields,
)
from app.repositories import RegistrationError
from registrar.errors import GraphError

logger = logging.getLogger(__name__)


async def cmd_resend(
    message: Message, registration_service, registration_repository, verified_student
):
    if verified_student:
        await message.answer("Your account is already registered. Use /me to view your own profile")
        return
    if await prompt_remaining_profile_fields(message, registration_repository):
        return
    try:
        status = await registration_service.resend(message.from_user.id)
    except RegistrationError as error:
        await message.answer(error_text(error))
        return
    except GraphError as error:
        logger.warning("Registration email unavailable (%s).", type(error).__name__)
        await message.answer(
            "Registration is temporarily unavailable\nWe couldn't send a verification email — please try again later"
        )
        return
    await code_prompt(message, status)


def create_router():
    router = Router(name=__name__)
    router.message.register(cmd_resend, Command("resend"))
    return router
