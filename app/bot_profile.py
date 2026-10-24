"""Explicit Telegram profile setup, separate from polling, Outlook, and the Mini App."""

import argparse
import asyncio
import json
from pathlib import Path

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import PRODUCTION, TEST
from aiogram.exceptions import TelegramAPIError
from aiogram.types import FSInputFile, InputProfilePhotoStatic

from app.commands import CommandMenu, chat_commands
from config import BotSettings
from registrar.config import ConfigurationError

NAME = "Social Registrar"
ABOUT = "Students and event registration for WIUT. Verify once and join events easily\n\nBy students, for students\nLovely, WestDevs"
DESCRIPTION = (
    "Join WIUT events in a few taps\n\n"
    "Register once with your student ID, then scan an event's QR code or open an invite link to join\n\n"
    "Hosting an event? \nUse /new_event with a name to create one and invite others!\n\n"
)
AVATAR = Path(__file__).parent / "assets" / "telegram-avatar.jpg"
DESCRIPTION_PICTURE = Path(__file__).parent / "assets" / "telegram-description.png"


async def apply_profile(bot: Bot, *, upload_photo=False) -> list[str]:
    name = await bot.get_my_name()
    description = await bot.get_my_description()
    about = await bot.get_my_short_description()
    changed = []
    if name.name != NAME:
        await bot.set_my_name(name=NAME)
        changed.append("name")
    if description.description != DESCRIPTION:
        await bot.set_my_description(description=DESCRIPTION)
        changed.append("description")
    if about.short_description != ABOUT:
        await bot.set_my_short_description(short_description=ABOUT)
        changed.append("about")
    await CommandMenu().install_defaults(bot)
    changed.append("command menu")
    if upload_photo:
        await bot.set_my_profile_photo(photo=InputProfilePhotoStatic(photo=FSInputFile(AVATAR)))
        changed.append("profile photo")
    return changed


async def configure(settings, *, upload_photo=False):
    session = AiohttpSession(api=TEST if settings.telegram_test_environment else PRODUCTION)
    async with Bot(settings.token, session=session) as bot:
        changed = await apply_profile(bot, upload_photo=upload_photo)
        print("Telegram profile configured: " + ", ".join(changed) + ".")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Preview or apply the bot's Telegram profile and command menu."
    )
    parser.add_argument("--env-file", type=Path, help="Path to the private .env file.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the profile to Telegram. Sends no chat messages.",
    )
    parser.add_argument(
        "--photo", action="store_true", help="Upload the bundled profile photo; requires --apply."
    )
    args = parser.parse_args(argv)
    if args.photo and not args.apply:
        parser.error("--photo requires --apply")
    if not args.apply:
        print(
            json.dumps(
                {
                    "name": NAME,
                    "about": ABOUT,
                    "description": DESCRIPTION,
                    "avatar": str(AVATAR),
                    "description_picture": str(DESCRIPTION_PICTURE),
                    "description_picture_setup": (
                        "In @BotFather: /mybots > your bot > Edit Bot > "
                        "Edit Description Picture. Upload this PNG as a photo. "
                        "The Bot API cannot set description pictures."
                    ),
                    "commands": [item.model_dump() for item in chat_commands()],
                },
                indent=2,
            )
        )
        return 0
    try:
        asyncio.run(configure(BotSettings.load(args.env_file), upload_photo=args.photo))
        return 0
    except (ConfigurationError, OSError, TelegramAPIError) as error:
        # Telegram transport exceptions may contain a URL with the token.
        print(
            f"Could not configure the Telegram profile ({type(error).__name__}). Check configuration and connectivity."
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
