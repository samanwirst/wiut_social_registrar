from aiogram import F, Router
from aiogram.types import Message, ReplyKeyboardRemove

from app.chat_formatting import card
from app.dialogs.registration import education_prompt, phone_prompt
from app.keyboards import main_menu
from app.repositories import RegistrationError


async def receive_contact(
    message: Message,
    registration_repository,
    verified_student,
    mini_app_url="",
    can_open_panel=False,
) -> None:
    if verified_student:
        await message.answer(
            "Your account is already registered. Use /me to view your own profile.",
            reply_markup=main_menu(mini_app_url, can_open_panel=can_open_panel),
        )
        return
    if await registration_repository.awaiting_education(message.from_user.id):
        await education_prompt(message)
        return
    if not await registration_repository.awaiting_phone(message.from_user.id):
        await message.answer(
            "Verify your Outlook email first. Send your student ID to begin registration.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return
    if message.forward_origin is not None:
        await phone_prompt(
            message,
            "Share your own Telegram contact using the button below; forwarded contacts cannot be used.",
        )
        return
    try:
        await registration_repository.save_contact(
            message.from_user.id,
            message.contact.user_id,
            message.contact.phone_number,
        )
    except RegistrationError as error:
        await phone_prompt(message, str(error))
        return
    await message.answer(
        **card(
            "Phone number saved", "One last step: choose your education level below."
        ).as_kwargs(),
        reply_markup=ReplyKeyboardRemove(),
    )
    await education_prompt(message)


def create_router() -> Router:
    router = Router(name=__name__)
    router.message.register(receive_contact, F.contact)
    return router
