"""Question rendering and reusable chat questionnaire transitions."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.formatting import Bold, Italic, Text

from app.chat_formatting import card, error_text, event_confirmation
from app.event_errors import EventError


def question_keyboard(step):
    question, rows = step.question, []
    kind = question["type"]
    if kind in {"single_choice", "multiple_choice"}:
        for index, option in enumerate(question["options"]):
            rows.append(
                [
                    InlineKeyboardButton(
                        text=option, callback_data=f"form:{step.token}:choose:{index}"
                    )
                ]
            )
    if not question["required"]:
        rows.append([InlineKeyboardButton(text="Skip", callback_data=f"form:{step.token}:skip")])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


async def send_question(message, step):
    question = step.question
    if step.index == 0 and step.event.description:
        await message.answer(**card(step.event.title, step.event.description).as_kwargs())
    instruction = {
        "text": "Send your answer as a message",
        "number": "Send a number as a message",
        "single_choice": "Choose one option below",
        "multiple_choice": "Choose one option below",
    }[question["type"]]
    text = Text(
        Bold(step.event.title),
        "\n",
        Italic(f"Question {step.index + 1}/{len(step.event.questions)}"),
        "\n\n",
        Bold(question["label"]),
        "\n\n",
        instruction,
    )
    if not question["required"]:
        text += Text("\n", Italic("Optional — you can skip this question"))
    if step.index == 0:
        text += Text(
            f". Answers are visible only to the organizer and kept for up to "
            f"{step.event.response_retention_days} days"
        )
    await message.answer(**text.as_kwargs(), reply_markup=question_keyboard(step))


async def resume_survey(message, event_survey, user_id=None):
    try:
        step = await event_survey.resume(user_id or message.from_user.id)
    except EventError as error:
        await message.answer(error_text(error))
        return True
    if step:
        await send_question(message, step)
    return step is not None


async def receive_answer(message, event_survey):
    try:
        step, completed = await event_survey.respond(message.from_user.id, text=message.text)
    except EventError as error:
        await message.answer(error_text(error))
        return
    if completed:
        await message.answer(**event_confirmation(completed).as_kwargs())
        await resume_survey(message, event_survey)
    else:
        await send_question(message, step)
