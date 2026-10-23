from aiogram import F, Router
from aiogram.types import Message

from app.chat_formatting import card, error_text
from app.dialogs.registration import (
    phone_prompt,
    prompt_remaining_profile_fields,
    request_code,
)
from app.dialogs.surveys import receive_answer, resume_survey
from app.repositories import RegistrationError


async def registration_text(
    message: Message,
    registration_repository,
    registration_service,
    verified_student,
    event_survey,
) -> None:
    if verified_student and await event_survey.active(message.from_user.id):
        await receive_answer(message, event_survey)
    elif verified_student:
        await message.answer("Use /me to view your own profile, or /help for instructions")
    elif await prompt_remaining_profile_fields(message, registration_repository):
        return
    elif await registration_repository.pending(message.from_user.id):
        try:
            await registration_repository.consume_code(message.from_user.id, message.text.strip())
        except RegistrationError as error:
            await message.answer(error_text(error))
            return
        await phone_prompt(message)
    else:
        await request_code(message, registration_service, message.text)


async def unsupported_message(
    message: Message, registration_repository, event_survey, verified_student
) -> None:
    if await event_survey.active(message.from_user.id):
        await resume_survey(message, event_survey)
    elif await prompt_remaining_profile_fields(message, registration_repository):
        return
    else:
        text = (
            "That command is not available. Use the Menu button or /help for the command list\n\n"
            if message.text and message.text.startswith("/")
            else (
                "Use /me to view your own profile, or /help for instructions"
                if verified_student
                else "Send your own student ID to register, or use /help for instructions"
            )
        )
        await message.answer(**card("Need a hand?", text).as_kwargs())


def create_router() -> Router:
    router = Router(name=__name__)
    router.message.register(registration_text, F.text, ~F.text.startswith("/"))
    router.message.register(unsupported_message)
    return router
