import logging

from aiogram import F, Router
from aiogram.types import Message

from app.services.registrar_service import RegistrarService
from app.handlers.contact_handler import phone_prompt
from app.handlers.education_handler import education_prompt
from app.handlers.verification_handler import request_code
from app.repositories import RegistrationError
from registrar.errors import GraphError
from app.handlers.survey_handler import receive_answer, resume_survey

logger = logging.getLogger(__name__)


async def answer_lookup(message: Message, student_id: str, service: RegistrarService, repository) -> None:
    try:
        student = await service.find_student(student_id)
    except ValueError as error:
        await repository.event(message.from_user.id, "lookup_failed", reason="invalid_id")
        await message.answer(str(error))
        return
    except GraphError as error:
        logger.warning("Student lookup failed (%s).", type(error).__name__)
        await repository.event(message.from_user.id, "lookup_failed", reason="graph_unavailable")
        await message.answer("Student lookup is temporarily unavailable. Please try again later.")
        return
    await repository.event(message.from_user.id, "lookup_succeeded" if student else "lookup_not_found", student)
    await message.answer(student.format() if student else "No student found with this ID.", parse_mode=None)


async def lookup_text(message: Message, registrar_service: RegistrarService, registration_repository,
                      registration_service, verified_student, event_survey) -> None:
    if verified_student and await event_survey.active(message.from_user.id):
        await receive_answer(message, event_survey)
    elif verified_student:
        await answer_lookup(message, message.text, registrar_service, registration_repository)
    elif await registration_repository.awaiting_education(message.from_user.id):
        await education_prompt(message)
    elif await registration_repository.awaiting_phone(message.from_user.id):
        await phone_prompt(message)
    elif await registration_repository.pending(message.from_user.id):
        try:
            await registration_repository.consume_code(message.from_user.id, message.text.strip())
        except RegistrationError as error:
            await message.answer(str(error))
            return
        await phone_prompt(message)
    else:
        await request_code(message, registration_service, message.text)


async def unsupported_message(message: Message, registration_repository, event_survey) -> None:
    if await event_survey.active(message.from_user.id):
        await resume_survey(message, event_survey)
    elif await registration_repository.awaiting_education(message.from_user.id):
        await education_prompt(message)
    elif await registration_repository.awaiting_phone(message.from_user.id):
        await phone_prompt(message)
    else:
        await message.answer("Send a student ID as text, or use /help for instructions.")


def create_router() -> Router:
    router = Router(name=__name__)
    router.message.register(lookup_text, F.text, ~F.text.startswith("/"))
    router.message.register(unsupported_message)
    return router
