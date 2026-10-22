from aiogram import F, Router
from aiogram.types import CallbackQuery
from aiogram.utils.formatting import Text

from app.chat_formatting import student_profile
from app.dialogs.messages import update_keyboard
from app.dialogs.surveys import resume_survey
from app.education import EDUCATION_LEVELS
from app.keyboards import main_menu
from app.repositories import RegistrationError


async def choose_education(
    callback: CallbackQuery,
    registration_repository,
    event_repository,
    event_survey,
    mini_app_url="",
    can_open_panel=False,
    command_menu=None,
):
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
    await update_keyboard(callback.message, None)
    text = student_profile(student, title="Registration complete", education_level=level)
    if pending_titles:
        pending_forms = await event_repository.pending_forms(callback.from_user.id)
        text += Text(
            "\n\nSaved events without extra questions have been registered. "
            "Complete the event questions below to finish the remaining registrations.\n"
            if pending_forms
            else "\n\nYour saved events have been registered.\n"
        ) + Text("\n".join(pending_titles))
    await callback.message.answer(
        **text.as_kwargs(), reply_markup=main_menu(mini_app_url, can_open_panel=can_open_panel)
    )
    if command_menu is not None:
        await command_menu.sync(
            callback.bot, callback.from_user.id, registered=True, organizer=can_open_panel
        )
    await resume_survey(callback.message, event_survey, callback.from_user.id)


def create_router():
    router = Router(name=__name__)
    router.callback_query.register(choose_education, F.data.startswith("education:"))
    return router
