import re

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.event_errors import EventError


def question_keyboard(step):
    question, rows = step.question, []
    kind, selected = question["type"], step.answers.get(question["id"], [])
    if kind in {"single_choice", "multiple_choice"}:
        action = "choose" if kind == "single_choice" else "toggle"
        for index, option in enumerate(question["options"]):
            label = ("✓ " if option in selected and kind == "multiple_choice" else "") + option
            rows.append([InlineKeyboardButton(text=label, callback_data=f"form:{step.token}:{action}:{index}")])
        if kind == "multiple_choice":
            rows.append([InlineKeyboardButton(text="Continue", callback_data=f"form:{step.token}:next")])
    if not question["required"]:
        rows.append([InlineKeyboardButton(text="Skip", callback_data=f"form:{step.token}:skip")])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


async def send_question(message, step):
    question = step.question
    if step.index == 0 and step.event.description:
        await message.answer(step.event.description, parse_mode=None)
    instruction = {"text": "Send your answer as a message.", "number": "Send a number as a message.",
        "single_choice": "Choose one option below.",
        "multiple_choice": "Choose one or more options below, then tap Continue."}[question["type"]]
    text = f"{step.event.title}\nQuestion {step.index + 1}/{len(step.event.questions)}\n\n{question['label']}\n\n{instruction}"
    if not question["required"]:
        text += " This question is optional."
    if step.index == 0:
        text += (f"\n\nAnswers are visible only to the organizer and kept for up to "
                 f"{step.event.response_retention_days} days. Use /cancel to leave this questionnaire.")
    await message.answer(text, parse_mode=None, reply_markup=question_keyboard(step))


async def resume_survey(message, event_survey, user_id=None):
    try:
        step = await event_survey.resume(user_id or message.from_user.id)
    except EventError as error:
        await message.answer(str(error))
        return True
    if step:
        await send_question(message, step)
    return step is not None


async def receive_answer(message, event_survey):
    try:
        step, completed = await event_survey.respond(message.from_user.id, text=message.text)
    except EventError as error:
        await message.answer(str(error))
        return
    if completed:
        await message.answer(f"You are registered for: {completed.title}", parse_mode=None)
        await resume_survey(message, event_survey)
    else:
        await send_question(message, step)


async def answer_callback(callback: CallbackQuery, event_survey):
    match = re.fullmatch(r"form:([a-f0-9]{16}):(choose|toggle|next|skip)(?::([0-9]{1,2}))?", callback.data or "")
    if match is None:
        await callback.answer("Invalid question button. Send /start to continue.", show_alert=True)
        return
    try:
        step, completed = await event_survey.respond(callback.from_user.id,
            token=match[1], action=match[2], option=int(match[3]) if match[3] is not None else None)
    except EventError as error:
        await callback.answer(str(error), show_alert=True)
        return
    await callback.answer()
    toggled = match[2] == "toggle"
    try:
        await callback.message.edit_reply_markup(reply_markup=question_keyboard(step) if toggled else None)
    except TelegramBadRequest as error:
        if "message is not modified" not in error.message.lower():
            raise
    if toggled:
        return
    if completed:
        await callback.message.answer(f"You are registered for: {completed.title}", parse_mode=None)
        await resume_survey(callback.message, event_survey, callback.from_user.id)
    else:
        await send_question(callback.message, step)


def create_router():
    router = Router(name=__name__)
    router.callback_query.register(answer_callback, F.data.startswith("form:"))
    return router
