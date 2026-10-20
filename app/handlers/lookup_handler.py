import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from app.services.registrar_service import RegistrarService
from registrar.errors import GraphError

logger = logging.getLogger(__name__)


async def answer_lookup(message: Message, student_id: str, service: RegistrarService) -> None:
    try:
        student = await service.find_student(student_id)
    except ValueError as error:
        await message.answer(str(error))
        return
    except GraphError as error:
        logger.warning("Student lookup failed: %s", error)
        await message.answer("Student lookup is temporarily unavailable. Please try again later.")
        return
    await message.answer(student.format() if student else "No student found with this ID.", parse_mode=None)


async def cmd_find(message: Message, command: CommandObject, registrar_service: RegistrarService) -> None:
    if not command.args:
        await message.answer("Usage: /find STUDENT_ID")
        return
    await answer_lookup(message, command.args, registrar_service)


async def lookup_text(message: Message, registrar_service: RegistrarService) -> None:
    await answer_lookup(message, message.text, registrar_service)


async def unsupported_message(message: Message) -> None:
    await message.answer("Send a student ID as text, or use /help for instructions.")


def create_router() -> Router:
    router = Router(name=__name__)
    router.message.register(cmd_find, Command("find"))
    router.message.register(lookup_text, F.text, ~F.text.startswith("/"))
    router.message.register(unsupported_message)
    return router
