from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.chat_formatting import card
from app.dialogs.messages import update_keyboard
from app.keyboards import main_menu


async def cmd_panel(message: Message, verified_student, mini_app_url, event_repository):
    if not verified_student:
        await message.answer("Complete registration first. Use /start to continue")
    elif not await event_repository.is_organizer(message.from_user.id):
        await message.answer(
            "Create your first form with /new_form Form name to unlock the organizer panel"
        )
    elif not mini_app_url:
        await message.answer("The organizer panel is not available yet. Please try again later")
    else:
        await message.answer(
            **card(
                "Organizer panel",
                "Manage forms, questions, tables and messages\n"
                "Choose a form in the panel to get started",
            ).as_kwargs(),
            reply_markup=main_menu(mini_app_url, can_open_panel=True),
        )


async def retired_event_menu(
    callback: CallbackQuery, mini_app_url, can_open_panel, verified_student
):
    """Replace buttons from older messages without restoring chat event lists or tables."""
    keyboard = main_menu(
        mini_app_url, can_open_panel=can_open_panel and verified_student is not None
    )
    await callback.answer(
        "Open the organizer panel to view your forms and people"
        if keyboard
        else "Use /panel to open the organizer panel",
        show_alert=keyboard is None,
    )
    await update_keyboard(callback.message, keyboard)


def create_router():
    router = Router(name=__name__)
    router.message.register(cmd_panel, Command("panel"))
    router.callback_query.register(
        retired_event_menu, F.data.startswith("members:") | F.data.startswith("member_events:")
    )
    return router
