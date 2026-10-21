from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.education import EDUCATION_LEVELS
from app.keyboards import main_menu
from app.repositories import RegistrationError
from app.handlers.survey_handler import resume_survey


async def education_prompt(message: Message) -> None:
    buttons = [InlineKeyboardButton(text=label, callback_data=f"education:{key}")
               for key, label in EDUCATION_LEVELS.items()]
    await message.answer("Select your current education level to finish registration:",
                         reply_markup=InlineKeyboardMarkup(inline_keyboard=[buttons[:2], buttons[2:]]))


async def choose_education(callback: CallbackQuery, registration_repository, event_repository, event_survey,
                           mini_app_url="", can_open_panel=False):
    level = EDUCATION_LEVELS.get((callback.data or "").removeprefix("education:"))
    if level is None:
        await callback.answer("Choose CIFS, Level 4, Level 5, or Level 6.", show_alert=True)
        return
    try:
        pending_titles = await event_repository.pending_titles(callback.from_user.id)
        student = await registration_repository.complete_registration(callback.from_user.id, level)
    except RegistrationError as error:
        await callback.answer(str(error), show_alert=True)
        return
    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest as error:
        if "message is not modified" not in error.message.lower():
            raise
    text = f"Registration complete!\n\n{student.format()}\nEducation level: {level}"
    if pending_titles:
        pending_forms = await event_repository.pending_forms(callback.from_user.id)
        text += ("\n\nSaved events without extra questions have been registered. "
                 "Complete the event questions below to finish the remaining registrations.\n" if pending_forms
                 else "\n\nYour saved events have been registered.\n") + "\n".join(pending_titles)
    await callback.message.answer(text, parse_mode=None, reply_markup=main_menu(mini_app_url, can_open_panel=can_open_panel))
    await resume_survey(callback.message, event_survey, callback.from_user.id)


def create_router():
    router = Router(name=__name__)
    router.callback_query.register(choose_education, F.data.startswith("education:"))
    return router
