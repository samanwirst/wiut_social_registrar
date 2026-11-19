"""Deliver a submitted attachment to its organizer without public download URLs."""

from aiogram.exceptions import TelegramAPIError

from app.chat_formatting import card, error_text
from app.event_errors import EventError
from app.media_answers import MEDIA_LABELS


async def show_attachment(message, repository, payload):
    try:
        title, label, student_id, attachment = await repository.attachment(
            message.from_user.id, payload
        )
        kind = attachment["kind"]
        if kind not in MEDIA_LABELS:
            raise EventError("This attachment is no longer available")
        await message.answer(
            **card(title, f"{student_id or 'Anonymous response'}\n{label}").as_kwargs()
        )
        kwargs = {kind: attachment["file_id"]}
        if kind != "video_note":
            kwargs.update(caption=attachment.get("caption"), parse_mode=None)
        await getattr(message.bot, "send_" + kind)(
            chat_id=message.from_user.id, **kwargs, request_timeout=30
        )
    except EventError as error:
        await message.answer(error_text(error))
    except TelegramAPIError:
        await message.answer("Could not open this attachment; check your chat before trying again")
