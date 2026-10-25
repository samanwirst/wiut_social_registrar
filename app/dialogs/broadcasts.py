"""Native Telegram composition, exact previews, and explicit audience confirmation."""

from aiogram.exceptions import TelegramAPIError
from aiogram.types import ForceReply, InlineKeyboardButton, InlineKeyboardMarkup, ReplyParameters

from app.chat_formatting import card, error_text, recipient_count
from app.dialogs.broadcast_content import send_preview
from app.event_errors import EventError


def confirmation(draft, *, can_send=True):
    suffix = f"{draft['id']}:{draft['revision']}"
    rows = []
    if can_send:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"Send to {recipient_count(draft['total'])}",
                    callback_data="bc:send:" + suffix,
                )
            ]
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            *rows,
            [
                InlineKeyboardButton(text="Edit message", callback_data="bc:edit:" + suffix),
            ],
        ]
    )


async def show_preview(message, repository, draft):
    available = True
    try:
        await message.bot.copy_message(
            chat_id=message.from_user.id,
            from_chat_id=message.from_user.id,
            message_id=draft["source_message_id"],
        )
    except TelegramAPIError:
        available = False
        await message.answer(
            "The saved preview is unavailable — choose Edit message to prepare it again"
        )
    await message.answer(
        **card(
            "Review your message",
            f"Audience: {recipient_count(draft['total'])}\nNothing is sent until you confirm",
        ).as_kwargs(),
        reply_markup=confirmation(draft, can_send=available),
    )


async def open_composer(message, repository, draft_id, *, edit=False):
    try:
        draft = await repository.get(message.from_user.id, draft_id)
        if draft["status"] == "preview" and not edit:
            await show_preview(message, repository, draft)
        elif draft["status"] in {"draft", "composing", "preview"}:
            prompt = await message.answer(
                **card(
                    "Write your message",
                    f"Reply here with your message for {recipient_count(draft['total'])}\n\nUse Telegram formatting, links, or a rich message\nA photo or document with a caption is supported too\n\nYou will see a preview before sending",
                ).as_kwargs(),
                reply_markup=ForceReply(
                    selective=True, input_field_placeholder="Write and format your message"
                ),
            )
            await repository.compose(message.from_user.id, draft_id, prompt.message_id)
        else:
            counts = draft["counts"]
            await message.answer(
                **card(
                    "Message status",
                    f"{draft['status'].capitalize()}\nSent: {counts.get('sent', 0)} of {draft['total']}\nFailed: {counts.get('failed', 0)}\nUnconfirmed: {counts.get('unknown', 0)}\n\nFinished messages appear at the bottom of the form's People tab",
                ).as_kwargs()
            )
    except EventError as error:
        await message.answer(error_text(error))


async def show_sent_message(message, repository, draft_id):
    try:
        draft = await repository.get(message.from_user.id, draft_id)
        if draft["status"] != "completed":
            raise EventError("This message has not finished sending")
        if draft["source_message_id"] is None:
            raise EventError("This message is no longer available")
        original = draft["original_message_id"]
        await message.bot.copy_message(
            chat_id=message.from_user.id,
            from_chat_id=message.from_user.id,
            message_id=draft["source_message_id"],
            reply_parameters=ReplyParameters(message_id=original, allow_sending_without_reply=True)
            if original is not None
            else None,
        )
    except EventError as error:
        await message.answer(error_text(error))
    except TelegramAPIError:
        await message.answer("Telegram couldn't open this message — it may have been deleted")


async def receive_message(message, repository, draft, event_repository):
    kind = next(
        (
            name
            for name in ["rich_message", "text", "photo", "document"]
            if getattr(message, name, None)
        ),
        None,
    )
    if kind is None or message.media_group_id:
        await message.answer(
            "Reply with one text or rich message, photo, or document — albums are not supported"
        )
        return
    try:
        event = await event_repository.settings(message.from_user.id, draft["event_id"])
        # Freeze both native content and attribution in the bot-owned preview before
        # confirmation. Later edits to the original or form name cannot change it.
        copied = await send_preview(message, event.title, kind)
        preview = await repository.preview(
            message.from_user.id,
            draft["id"],
            message.reply_to_message.message_id,
            copied.message_id,
            kind,
            original_message_id=message.message_id,
        )
    except TelegramAPIError:
        await message.answer(
            "Telegram couldn't prepare this preview — send another message as a reply"
        )
        return
    except EventError as error:
        await message.answer(error_text(error))
        return
    await message.answer(
        **card(
            "Review your message",
            f"This message will be sent to {recipient_count(preview['total'])}\nConfirm when you are ready",
        ).as_kwargs(),
        reply_markup=confirmation(preview),
    )
