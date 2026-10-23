"""Telegram command catalog and bounded synchronization of private-chat menus."""

import logging
from collections import OrderedDict
from time import monotonic

from aiogram.exceptions import TelegramAPIError
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
    BotCommandScopeDefault,
    MenuButtonCommands,
)

logger = logging.getLogger(__name__)

COMMANDS = {
    "start": "Start or resume registration",
    "new_event": "Create an event",
    "panel": "Events and participants",
    "resend": "Resend email code",
    "me": "View your own student profile",
    "help": "Help and commands",
    "info": "About the bot and project",
}


def chat_commands(*, registered=False, organizer=False) -> list[BotCommand]:
    names = ["start"]
    if registered:
        names.append("new_event")
        if organizer:
            names.append("panel")
    else:
        names.append("resend")
    if registered:
        names.append("me")
    names.extend(("help", "info"))
    descriptions = {**COMMANDS, "start": "Start the bot"} if registered else COMMANDS
    return [BotCommand(command=name, description=descriptions[name]) for name in names]


class CommandMenu:
    """Update only when a user's visible menu changes, with bounded memory and retries."""

    def __init__(self, *, clock=monotonic, ttl=3600, max_entries=4096):
        self.clock, self.ttl, self.max_entries = clock, ttl, max_entries
        self._synced = OrderedDict()

    async def install_defaults(self, bot) -> None:
        # The bot operates in private chats; group chats do not inherit its commands.
        await bot.set_my_commands([], scope=BotCommandScopeDefault(), request_timeout=5)
        await bot.set_my_commands(
            chat_commands(), scope=BotCommandScopeAllPrivateChats(), request_timeout=5
        )
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands(), request_timeout=5)

    async def sync(self, bot, user_id: int, *, registered=False, organizer=False) -> None:
        context = (bool(registered), bool(registered and organizer))
        cached = self._synced.get(user_id)
        now = self.clock()
        if cached is not None and cached[0] == context and cached[1] > now:
            self._synced.move_to_end(user_id)
            return
        try:
            await bot.set_my_commands(
                chat_commands(registered=context[0], organizer=context[1]),
                scope=BotCommandScopeChat(chat_id=user_id),
                request_timeout=5,
            )
        except TelegramAPIError as error:
            # A cosmetic failure must never block a registration or expose token-bearing errors.
            logger.warning("Could not update the command menu (%s).", type(error).__name__)
            return
        self._synced[user_id] = (context, now + self.ttl)
        self._synced.move_to_end(user_id)
        while len(self._synced) > self.max_entries:
            self._synced.popitem(last=False)
