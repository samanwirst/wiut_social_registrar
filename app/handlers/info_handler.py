from pathlib import Path

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.formatting import Bold, Italic, Text, TextLink

INFO_PICTURE = Path(__file__).resolve().parents[1] / "assets" / "telegram-info.png"


async def cmd_info(message: Message) -> None:
    content = Text(
        Bold("Social Registrar"),
        "\n",
        Italic("By students, for students"),
        "\n\n",
        Bold("Your next campus moment"),
        "\nVerify once for WIUT events, advisor applications and more\n"
        "Answer form questions right here in chat\n\n",
        Bold("Bring people together"),
        "\nCreate forms, edit response tables and message selected people in your organizer panel\n\n",
        "Designed and developed by\n",
        TextLink("Mukhammadiev Samandar", url="https://t.me/samanwirst"),
        ", ",
        TextLink("WestDevs", url="https://t.me/westdevs"),
        "\n\n",
        "Lovely,",
        "\n",
        Bold("WestDevs Team"),
        "🤍",
    )
    await message.answer_photo(
        photo=FSInputFile(INFO_PICTURE),
        **content.as_kwargs(text_key="caption", entities_key="caption_entities"),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="WestDevs", url="https://t.me/westdevs"),
                    InlineKeyboardButton(
                        text="GitHub", url="https://github.com/samanwirst/wiut_social_registrar"
                    ),
                ]
            ]
        ),
    )


def create_router() -> Router:
    router = Router(name=__name__)
    router.message.register(cmd_info, Command("info"))
    return router
