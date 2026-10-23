from aiogram import Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import Message, ReplyKeyboardRemove

from app.chat_formatting import card, error_text, event_confirmation
from app.dialogs.registration import code_prompt, prompt_remaining_profile_fields, welcome
from app.dialogs.surveys import resume_survey, send_question
from app.event_repository import EventError, event_id_from_payload
from app.keyboards import main_menu


async def cmd_start(
    message: Message,
    command: CommandObject,
    registration_repository,
    event_repository,
    verified_student,
    event_survey,
    mini_app_url="",
    can_open_panel=False,
) -> None:
    await registration_repository.event(message.from_user.id, "bot_started")
    if command.args:
        try:
            event_id = event_id_from_payload(command.args)
            event, status = await event_repository.visit(message.from_user.id, event_id)
        except EventError as error:
            await message.answer(error_text(error))
            return
        if status == "needs_form":
            try:
                step = await event_survey.begin(message.from_user.id, event.id)
            except EventError as error:
                await message.answer(error_text(error))
                return
            if step:
                await send_question(message, step)
            return
        if status != "pending":
            await message.answer(
                **event_confirmation(event, already=status != "registered").as_kwargs(),
                reply_markup=main_menu(mini_app_url, can_open_panel=can_open_panel),
            )
            return
        await message.answer(
            **card(
                f"Event saved: {event.title}",
                "Complete your student registration below\n"
                "Then answer any event questions here to finish joining",
            ).as_kwargs(),
        )
    if verified_student:
        if not await resume_survey(message, event_survey):
            await message.answer(
                "You're all set! Scan the QR code to join, or use /help",
                reply_markup=ReplyKeyboardRemove(),
            )
    elif await prompt_remaining_profile_fields(message, registration_repository):
        return
    elif await registration_repository.pending(message.from_user.id):
        await code_prompt(message, "pending")
    else:
        await welcome(message)


def create_router() -> Router:
    router = Router(name=__name__)
    router.message.register(cmd_start, CommandStart())
    return router
