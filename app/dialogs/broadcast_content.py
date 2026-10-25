"""Prepare native Telegram previews with a literal, italic form attribution."""

from aiogram.types import InputRichMessage, MessageEntity

from app.event_errors import EventError


def _utf16_length(text):
    return len(text.encode("utf-16-le")) // 2


def _signed_text(text, entities, title, limit):
    footer = f"By {title}"
    prefix = text + "\n\n" if text else ""
    signed = prefix + footer
    if _utf16_length(signed) > limit:
        raise EventError("Shorten your message to leave room for the form name, then reply again")
    return signed, [
        *(entities or []),
        MessageEntity(type="italic", offset=_utf16_length(prefix), length=_utf16_length(footer)),
    ]


def _input_rich_value(value):
    """Reuse embedded files through input media, including inside nested rich blocks."""
    if isinstance(value, list):
        return [_input_rich_value(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: _input_rich_value(item) for key, item in value.items()}
    kind = value.get("type")
    if kind in {"photo", "video", "animation", "audio", "document", "voice_note"}:
        media = value[kind]
        if kind == "photo":
            media = max(media, key=lambda size: size["width"] * size["height"])
        result[kind] = {"type": kind, "media": media["file_id"]}
        if "has_spoiler" in result:
            result[kind]["has_spoiler"] = result.pop("has_spoiler")
    return result


async def send_preview(message, title, kind):
    """Create one bot-owned message; recipients later receive this exact saved preview."""
    bot, owner = message.bot, message.from_user.id
    if kind == "rich_message":
        content = _input_rich_value(message.rich_message.model_dump(mode="json", exclude_none=True))
        content["blocks"].append(
            {"type": "paragraph", "text": {"type": "italic", "text": f"By {title}"}}
        )
        return await bot.send_rich_message(
            chat_id=owner,
            rich_message=InputRichMessage.model_validate(
                {**content, "skip_entity_detection": True}
            ),
            allow_paid_broadcast=False,
        )
    if kind == "text":
        text, entities = _signed_text(message.text, message.entities, title, 4096)
        return await bot.send_message(
            chat_id=owner,
            text=text,
            entities=entities,
            parse_mode=None,
            link_preview_options=message.link_preview_options,
            allow_paid_broadcast=False,
        )
    caption, entities = _signed_text(message.caption or "", message.caption_entities, title, 1024)
    return await bot.copy_message(
        chat_id=owner,
        from_chat_id=message.chat.id,
        message_id=message.message_id,
        caption=caption,
        caption_entities=entities,
        parse_mode=None,
        show_caption_above_media=message.show_caption_above_media,
        allow_paid_broadcast=False,
    )
