"""Bounded Telegram attachment references; file bytes and bot credentials stay out of answers."""

import re
from uuid import UUID

from app.event_errors import EventError

MEDIA_LABELS = {
    "photo": "Photo",
    "document": "File",
    "voice": "Voice message",
    "video": "Video",
    "audio": "Audio",
    "animation": "GIF",
    "video_note": "Video message",
}
MEDIA_QUESTIONS = {*MEDIA_LABELS, "media"}
MEDIA_INSTRUCTIONS = {
    "photo": "Send one photo",
    "document": "Send one file",
    "voice": "Send one voice message",
    "video": "Send one video",
    "audio": "Send one audio file",
    "animation": "Send one GIF",
    "video_note": "Send one video message",
    "media": "Send one photo, file, voice message, video or audio",
}


def attachment_from_message(message):
    if message.media_group_id:
        raise EventError("Send one attachment at a time, without an album")
    for kind in ("photo", "animation", "video", "voice", "video_note", "audio", "document"):
        value = getattr(message, kind, None)
        if value:
            if kind == "photo":
                value = max(value, key=lambda photo: photo.width * photo.height)
            result = {
                "kind": kind,
                "file_id": value.file_id,
                "file_unique_id": value.file_unique_id,
            }
            for key in ("file_name", "mime_type", "file_size", "duration", "width", "height"):
                item = getattr(value, key, None)
                if item is not None:
                    result[key] = item
            if message.caption:
                result["caption"] = message.caption
            return result
    return None


def validate_attachment(question, value):
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("kind"), str)
        or value["kind"] not in MEDIA_LABELS
    ):
        raise EventError(MEDIA_INSTRUCTIONS[question["type"]])
    if question["type"] != "media" and value["kind"] != question["type"]:
        raise EventError(MEDIA_INSTRUCTIONS[question["type"]])
    limits = {
        "file_id": 1024,
        "file_unique_id": 256,
        "file_name": 255,
        "mime_type": 255,
        "caption": 1024,
    }
    allowed = {"kind", *limits, "file_size", "duration", "width", "height"}
    if set(value) - allowed:
        raise EventError("Send a supported attachment using Telegram")
    for key, limit in limits.items():
        item = value.get(key)
        if item is None and key not in {"file_id", "file_unique_id"}:
            continue
        if not isinstance(item, str) or not 1 <= len(item) <= limit:
            raise EventError("This attachment is invalid; send it again using Telegram")
    for key in ("file_size", "duration", "width", "height"):
        if key in value and (type(value[key]) is not int or not 0 <= value[key] < 2**53):
            raise EventError("This attachment is invalid; send it again using Telegram")
    return dict(value)


def public_attachment(value, registration_id, question_id):
    """Expose presentation metadata and an owner-checked bot link payload, never a file ID."""
    payload = f"file_{registration_id}_{question_id.replace('-', '')}"
    return {
        key: item for key, item in value.items() if key not in {"file_id", "file_unique_id"}
    } | {"payload": payload}


def attachment_reference(payload):
    match = re.fullmatch(r"file_([1-9][0-9]{0,18})_([a-f0-9]{32})", payload)
    if match and int(match[1]) < 2**63:
        return int(match[1]), str(UUID(match[2]))
    raise EventError("This attachment link is invalid")
