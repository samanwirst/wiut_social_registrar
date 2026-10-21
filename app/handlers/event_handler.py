import asyncio

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo
from aiogram.utils.deep_linking import create_start_link

from app.event_repository import EventError
from app.handlers.contact_handler import phone_prompt
from app.handlers.education_handler import education_prompt
from app.services.event_service import event_qr


async def new_event(message: Message, event_repository, registration_repository, verified_student,
                    command: CommandObject | None = None, mini_app_url=""):
    if not verified_student:
        if await registration_repository.awaiting_education(message.from_user.id):
            await education_prompt(message)
        elif await registration_repository.awaiting_phone(message.from_user.id):
            await phone_prompt(message)
        else:
            await message.answer("Complete registration first. Send /start, then your own student ID.")
        return
    title = command.args if command and command.args else "New Event"
    try:
        event = await event_repository.create(message.from_user.id, title)
    except EventError as error:
        await message.answer(str(error))
        return
    link = await create_start_link(message.bot, "event_" + event.id)
    png = await asyncio.to_thread(event_qr, link)
    rows = [[InlineKeyboardButton(text="Register for event", url=link)]]
    if mini_app_url:
        rows.append([InlineKeyboardButton(text="Manage event", web_app=WebAppInfo(url=f"{mini_app_url}/?event={event.id}"))])
    await message.answer_photo(
        BufferedInputFile(png, filename=f"event-{event.id}.png"),
        caption=f"{event.title}\n\nShare this QR code or link to register for the event:\n{link}",
        parse_mode=None,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


def create_router() -> Router:
    router = Router(name=__name__)
    router.message.register(new_event, Command("new_event"))
    return router
