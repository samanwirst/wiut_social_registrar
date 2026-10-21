from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message


async def cmd_help(message: Message, can_open_panel=False) -> None:
    panel_help = ("/panel opens the organizer Mini App to edit events and questions and view participants and answers.\n\n"
                  if can_open_panel else "")
    await message.answer(
        "Registration\n\n"
        "1. Send your student ID as text. Keep any leading zeroes.\n"
        "2. Open your Outlook mailbox and find the verification email.\n"
        "3. Send the 6-digit code here to verify your email.\n"
        "4. Tap Share phone number to share your own Telegram contact.\n"
        "5. Select CIFS, Level 4, Level 5, or Level 6 using the inline buttons to complete registration.\n\n"
        "Codes expire after 10 minutes and allow 5 incorrect attempts.\n"
        "/resend requests a new code; /cancel changes the pending student ID.\n"
        "After registration, send an ID to look up a profile, or use /start for your own profile.\n\n"
        "Events\n\n"
        "Use /new_event Event name to create an event and get its QR code.\n"
        "Open an event QR link and press Start if Telegram asks. Registered students are enrolled "
        "automatically; new users finish student registration first. Repeated scans do not create duplicates.\n\n"
        "Events with extra questions ask them here in chat before enrollment. "
        "Reply to text questions with a message and use inline buttons for choices. "
        "Use /start to resume or /cancel to leave a questionnaire.\n"
        f"{panel_help}"
    )


def create_router() -> Router:
    router = Router(name=__name__)
    router.message.register(cmd_help, Command("help"))
    return router
