"""Transport access checks and dynamic user context for aiogram handlers."""

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message


class PrivateChatMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: Message | CallbackQuery, data):
        if isinstance(event, CallbackQuery):
            if (
                event.from_user.is_bot
                or not isinstance(event.message, Message)
                or event.message.chat.type != "private"
                or event.message.chat.id != event.from_user.id
            ):
                await event.answer("Open a private chat with the bot to continue", show_alert=True)
                return
        else:
            if event.chat.type != "private":
                await event.answer(
                    "Please open a private chat with the bot to register or view your own profile"
                )
                return
            if event.from_user is None or event.from_user.is_bot:
                return
        return await handler(event, data)


class UserContextMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: Message | CallbackQuery, data):
        repository = data["registration_repository"]
        await repository.touch_user(event.from_user)
        data["verified_student"] = await repository.verified(event.from_user.id)
        data["can_open_panel"] = bool(data["mini_app_url"]) and await data[
            "event_repository"
        ].is_organizer(event.from_user.id)
        return await handler(event, data)


class CommandMenuMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: Message | CallbackQuery, data):
        await data["command_menu"].sync(
            data["bot"],
            event.from_user.id,
            registered=data["verified_student"] is not None,
            organizer=data["can_open_panel"],
        )
        return await handler(event, data)
