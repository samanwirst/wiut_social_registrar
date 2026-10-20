import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardRemove

from app.handlers.contact_handler import phone_prompt
from app.repositories import RegistrationError
from registrar.errors import GraphError

logger = logging.getLogger(__name__)


async def code_prompt(message, status):
    text = ("Check the Outlook mailbox linked to your student ID and enter the 6-digit code here. "
            "The code expires in 10 minutes.\nUse /resend for a new code or /cancel to change your ID.")
    if status == "unknown":
        text = ("Microsoft did not confirm submission. If the verification email arrives in Outlook, "
                "enter its 6-digit code here. Otherwise, wait 60 seconds and use /resend.")
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


async def cmd_resend(message: Message, registration_service, registration_repository, verified_student):
    if verified_student:
        await message.answer("Your account is already registered. Use /start to see your profile.")
        return
    if await registration_repository.awaiting_phone(message.from_user.id):
        await phone_prompt(message)
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


async def cmd_cancel(message: Message, registration_repository, verified_student):
    if verified_student:
        await message.answer("Your account is already registered. Use /start to see your profile.")
        return
    await registration_repository.cancel(message.from_user.id)
    await message.answer("Registration cancelled. Send your student ID to start again.",
                         reply_markup=ReplyKeyboardRemove())


def create_router():
    router = Router(name=__name__)
    router.message.register(cmd_resend, Command("resend"))
    router.message.register(cmd_cancel, Command("cancel"))
    return router
