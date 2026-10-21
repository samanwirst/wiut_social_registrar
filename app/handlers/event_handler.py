from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)
from aiogram.utils.formatting import Bold, Text

from app.dialogs.registration import prompt_remaining_profile_fields
from app.event_repository import EventError


async def new_event(
    message: Message,
    event_repository,
    registration_repository,
    verified_student,
    command: CommandObject | None = None,
    mini_app_url="",
    command_menu=None,
):
    if not verified_student:
        if not await prompt_remaining_profile_fields(message, registration_repository):
            await message.answer(
                "Complete registration first. Send /start, then your own student ID."
            )
        return
    title = command.args if command and command.args else "New Event"
    try:
        event = await event_repository.create(message.from_user.id, title)
    except EventError as error:
        await message.answer(str(error))
        return
    text = Text(
        Bold("Congratulations! Event created 🎉"),
        "\n\n",
        Bold(event.title),
        "\n\nManage registration process from your event panel:\n",
        "• Edit event details and add questions\n",
        "• Get your QR code and invite link\n",
        "• View participants and their answers\n\n",
    )
    rows = []
    if mini_app_url:
        text += Text("Tap Manage event below to open the panel\nYou can return anytime with /panel")
        rows.append(
            [
                InlineKeyboardButton(
                    text="Manage event", web_app=WebAppInfo(url=f"{mini_app_url}/?event={event.id}")
                )
            ]
        )
    else:
        text += Text("The event panel is currently unavailable. Your event has been saved.")
    await message.answer(
        **text.as_kwargs(),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows) if rows else None,
    )
    if command_menu is not None:
        await command_menu.sync(
            message.bot, message.from_user.id, registered=True, organizer=bool(mini_app_url)
        )


def create_router() -> Router:
    router = Router(name=__name__)
    router.message.register(new_event, Command("new_event"))
    return router
