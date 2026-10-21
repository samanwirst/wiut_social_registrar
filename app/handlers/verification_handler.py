import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardRemove

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
        await message.answer("Your account is already registered. Use /start to see your profile.")
        return
    if await prompt_remaining_profile_fields(message, registration_repository):
        return
    try:
        status = await registration_service.resend(message.from_user.id)
    except RegistrationError as error:
        await message.answer(str(error))
        return
    except GraphError as error:
        logger.warning("Registration email unavailable (%s).", type(error).__name__)
        await message.answer("Registration is temporarily unavailable. Please try again later.")
        return
    await code_prompt(message, status)


async def cmd_cancel(message: Message, registration_repository, verified_student, event_survey):
    if await event_survey.cancel(message.from_user.id):
        await message.answer(
            "Event questionnaire cancelled. Open the event link again to restart it."
        )
        return
    if verified_student:
        await message.answer("Your account is already registered. Use /start to see your profile.")
        return
    try:
        await registration_repository.cancel(message.from_user.id)
    except RegistrationError as error:
        await message.answer(str(error))
        return
    await message.answer(
        "Registration cancelled. Send your student ID to start again.",
        reply_markup=ReplyKeyboardRemove(),
    )


def create_router():
    router = Router(name=__name__)
    router.message.register(cmd_resend, Command("resend"))
    router.message.register(cmd_cancel, Command("cancel"))
    return router
