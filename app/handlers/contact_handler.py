from aiogram import F, Router
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove

from app.repositories import RegistrationError
from app.keyboards import main_menu
from app.handlers.education_handler import education_prompt


async def phone_prompt(message: Message, text: str | None = None) -> None:
    await message.answer(
        text or "Your email is verified. Next, tap Share phone number below "
                "to share your own Telegram contact. Your number will be saved with your profile.\n"
                "Use /cancel to change your student ID.",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="Share phone number", request_contact=True)]],
            resize_keyboard=True, one_time_keyboard=True,
        ),
    )


async def receive_contact(message: Message, registration_repository, verified_student, mini_app_url="", can_open_panel=False) -> None:
    if verified_student:
        await message.answer("Your account is already registered. Use /start to see your profile.",
                             reply_markup=main_menu(mini_app_url, can_open_panel=can_open_panel))
        return
    if await registration_repository.awaiting_education(message.from_user.id):
        await education_prompt(message)
        return
    if not await registration_repository.awaiting_phone(message.from_user.id):
        await message.answer("Verify your Outlook email first. Send your student ID to begin registration.",
                             reply_markup=ReplyKeyboardRemove())
        return
    if message.forward_origin is not None:
        await phone_prompt(message, "Share your own Telegram contact using the button below; forwarded contacts cannot be used.")
        return
    try:
        await registration_repository.save_contact(
            message.from_user.id, message.contact.user_id, message.contact.phone_number,
        )
    except RegistrationError as error:
        await phone_prompt(message, str(error))
        return
    await message.answer("Phone number saved.", reply_markup=ReplyKeyboardRemove())
    await education_prompt(message)


def create_router() -> Router:
    router = Router(name=__name__)
    router.message.register(receive_contact, F.contact)
    return router
