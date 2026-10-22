import re

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.chat_formatting import event_confirmation
from app.dialogs.messages import update_keyboard
from app.dialogs.surveys import question_keyboard, resume_survey, send_question
from app.event_errors import EventError


async def answer_callback(callback: CallbackQuery, event_survey):
    match = re.fullmatch(
        r"form:([a-f0-9]{16}):(choose|toggle|next|skip)(?::([0-9]{1,2}))?", callback.data or ""
    )
    if match is None:
        await callback.answer("Invalid question button. Send /start to continue.", show_alert=True)
        return
    try:
        step, completed = await event_survey.respond(
            callback.from_user.id,
            token=match[1],
            action=match[2],
            option=int(match[3]) if match[3] is not None else None,
        )
    except EventError as error:
        await callback.answer(str(error), show_alert=True)
        return
    await callback.answer()
    toggled = match[2] == "toggle"
    await update_keyboard(callback.message, question_keyboard(step) if toggled else None)
    if toggled:
        return
    if completed:
        await callback.message.answer(**event_confirmation(completed).as_kwargs())
        await resume_survey(callback.message, event_survey, callback.from_user.id)
    else:
        await send_question(callback.message, step)


def create_router():
    router = Router(name=__name__)
    router.callback_query.register(answer_callback, F.data.startswith("form:"))
    return router
