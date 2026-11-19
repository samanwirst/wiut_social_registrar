from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, ReplyKeyboardRemove


async def cmd_cancel(
    message: Message, registration_repository, verified_student, state: FSMContext
):
    await registration_repository.cancel_current(message.from_user.id)
    await state.clear()
    await message.answer(
        "Cancelled\n\nScan a form QR code to continue, or use /me"
        if verified_student
        else "Cancelled\n\nUse /start when you're ready",
        reply_markup=ReplyKeyboardRemove(),
    )


def create_router():
    router = Router(name=__name__)
    router.message.register(cmd_cancel, Command("cancel"))
    return router
