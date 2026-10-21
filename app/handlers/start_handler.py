from aiogram import Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import Message, ReplyKeyboardRemove

from app.dialogs.registration import prompt_remaining_profile_fields
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
    if verified_student:
        # Inline markup cannot remove a reply keyboard left by an older bot version.
        await message.answer(
            "Create an event with /new_event Event name.", reply_markup=ReplyKeyboardRemove()
        )
    if command.args:
        try:
            event_id = event_id_from_payload(command.args)
            event, status = await event_repository.visit(message.from_user.id, event_id)
        except EventError as error:
            await message.answer(str(error))
            return
        if status == "needs_form":
            try:
                step = await event_survey.begin(message.from_user.id, event.id)
            except EventError as error:
                await message.answer(str(error))
                return
            if step:
                await send_question(message, step)
            return
        if status != "pending":
            text = (
                "You are registered for"
                if status == "registered"
                else "You are already registered for"
            )
            await message.answer(
                f"{text}: {event.title}",
                parse_mode=None,
                reply_markup=main_menu(mini_app_url, can_open_panel=can_open_panel),
            )
            return
        await message.answer(
            f"Event saved: {event.title}\nComplete your student registration below. "
            "You will then be registered for this event automatically.",
            parse_mode=None,
        )
    if verified_student:
        await message.answer(
            "Your verified profile:\n\n" + verified_student.format(),
            parse_mode=None,
            reply_markup=main_menu(mini_app_url, can_open_panel=can_open_panel),
        )
        await resume_survey(message, event_survey)
    elif await prompt_remaining_profile_fields(message, registration_repository):
        return
    elif await registration_repository.pending(message.from_user.id):
        await message.answer(
            "Open Outlook and send the 6-digit verification code here.\n"
            "Use /resend for a new code or /cancel to change your student ID."
        )
    else:
        await message.answer(
            "Welcome! Send your own student ID to register. Keep any leading zeroes.\n\n"
            "We will email a 6-digit code to the Outlook mailbox linked to your ID. "
            "Open Outlook and enter that code here, then share your phone number "
            "using the Telegram contact button, and select your current education level.",
            reply_markup=ReplyKeyboardRemove(),
        )


def create_router() -> Router:
    router = Router(name=__name__)
    router.message.register(cmd_start, CommandStart())
    return router
