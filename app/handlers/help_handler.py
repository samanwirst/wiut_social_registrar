from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.utils.formatting import Bold, Code, Text

from app.commands import chat_commands


async def cmd_help(message: Message, can_open_panel=False, verified_student=None) -> None:
    text = Text()
    if verified_student is None:
        text += Text(
            Bold("Register once"),
            "\n",
            "1. Send your student ID, including leading zeroes\n",
            "2. Enter the 6-digit code from your Outlook email\n",
            "3. Tap Share phone number to share your own contact\n",
            "4. Choose your current education level\n\n",
            "Codes expire after 10 minutes and allow 5 incorrect attempts\n\n",
        )
    else:
        text += Text(
            Bold("Your profile"),
            "\n",
            "Use /me to view your own verified student profile\n\n",
        )
    text += Text(
        Bold("Open a form"),
        "\n",
        "Scan its QR code with your camera and open the bot (tap Start if Telegram asks)\n",
        "Answer its questions here in chat\n\n",
        Bold("Create a form"),
        "\n",
        "Create an event or advisor application form with ",
        Code("/new_form [form name]"),
        "\n",
    )
    if can_open_panel:
        text += Text("Use /panel to manage forms, editable tables and messages\n")
    text += Text("\n", Bold("Commands"), "\n")
    commands = chat_commands(registered=verified_student is not None, organizer=can_open_panel)
    text += Text("\n".join(f"/{item.command} — {item.description}" for item in commands))
    text += Text(
        "\n\nForm organizers can see their respondents' contact details and answers",
    )
    await message.answer(**text.as_kwargs())


def create_router() -> Router:
    router = Router(name=__name__)
    router.message.register(cmd_help, Command("help"))
    return router
