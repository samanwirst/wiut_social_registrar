from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.utils.formatting import Bold, Text

from app.commands import chat_commands


async def cmd_help(message: Message, can_open_panel=False, verified_student=None) -> None:
    text = Text()
    if verified_student is None:
        text += Text(
            Bold("Register once"),
            "\n",
            "1. Send your student ID, including leading zeroes\n",
            "2. Enter the code from your university email\n",
            "3. Share your phone number using the button\n",
            "4. Choose your current education level\n\n",
        )
    text += Text(
        Bold("Take part"),
        "\n",
        "Open the link or scan the QR code you received\n",
        "Answer its questions here in chat\n\n",
    )
    if can_open_panel:
        text += Text(
            Bold("Your forms"),
            "\nUse /panel to manage your forms and participants\n\n",
        )
    text += Text(Bold("Commands"), "\n")
    commands = chat_commands(registered=verified_student is not None, organizer=can_open_panel)
    text += Text("\n".join(f"/{item.command} — {item.description}" for item in commands))
    text += Text(
        "\n\nOrganizers can see your contact details and answers",
    )
    await message.answer(**text.as_kwargs())


def create_router() -> Router:
    router = Router(name=__name__)
    router.message.register(cmd_help, Command("help"))
    return router
