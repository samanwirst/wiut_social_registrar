"""A deliberately small, typed vocabulary; never accept arbitrary analytics payloads."""

import re
from uuid import UUID, uuid4

from app.analytics.models import UsageEvent

SERVER_EVENTS = frozenset(
    {
        "form_opened",
        "form_started",
        "form_resumed",
        "form_switched",
        "form_completed",
        "question_reached",
        "question_answered",
        "question_rejected",
        "form_created",
        "form_updated",
        "conversation_cancelled",
        "chat_action",
        "http_request",
        "telegram_request",
        "email_lookup",
        "broadcast_queued",
        "broadcast_delivery",
        "qr_generation",
        "file_delivery",
        "registration_prompt",
        "registration_rejected",
        "form_rejected",
    }
)
CLIENT_EVENTS = frozenset(
    {"panel_opened", "screen_view", "screen_engagement", "ui_action", "client_error"}
)
SCREENS = frozenset(
    {"forms", "overview", "questions", "participants", "qr", "answer", "columns", "messages"}
)
ACTIONS = frozenset(
    {
        "start",
        "new_form",
        "new_event",
        "panel",
        "me",
        "help",
        "info",
        "resend",
        "cancel",
        "other_command",
        "text",
        "contact",
        "attachment",
        "other_message",
        "education",
        "form_choose",
        "form_toggle",
        "form_next",
        "form_skip",
        "broadcast_send",
        "broadcast_edit",
        "other_callback",
        "open_form",
        "back_to_forms",
        "page_previous",
        "page_next",
        "refresh",
        "save_form",
        "add_question",
        "remove_question",
        "reorder_question",
        "question_type",
        "add_option",
        "remove_option",
        "open_columns",
        "save_columns",
        "add_column",
        "remove_column",
        "select_all",
        "select_person",
        "prepare_message",
        "export_xlsx",
        "edit_answer",
        "save_answer",
        "discard_answer",
        "open_answer",
        "download_qr",
        "transparent_background",
        "generate_design",
        "standard_qr",
        "copy_link",
        "open_media",
        "open_message",
        "close_answer",
        "other_control",
        "field_interaction",
        "accept_registrations",
        "anonymous_mode",
        "required_question",
    }
)
KINDS = frozenset(
    {
        "text",
        "number",
        "single_choice",
        "multiple_choice",
        "photo",
        "document",
        "voice",
        "video",
        "audio",
        "animation",
        "video_note",
        "media",
        "unknown",
        "rich_message",
    }
)
ERRORS = frozenset(
    {
        "validation",
        "authorization",
        "not_found",
        "rate_limit",
        "conflict",
        "network",
        "timeout",
        "database",
        "telegram",
        "outlook",
        "internal",
        "aborted",
        "unknown",
        "closed",
        "expired",
        "stale_button",
    }
)


def identifier(value):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return None


def properties(data):
    """Whitelist values too: even an innocent field must not become a text-content channel."""
    result = {}
    categories = {
        "action": ACTIONS,
        "screen": SCREENS,
        "kind": KINDS,
        "error": ERRORS,
        "platform": {"android", "ios", "tdesktop", "macos", "weba", "webk", "web", "unknown"},
        "stage": {"student_id", "email", "phone", "education", "registered"},
        "status": {"accepted", "failed", "unknown", "sent", "ready", "cancelled", "queued"},
        "entry": {"invite", "direct", "compose", "file", "message"},
    }
    for key, choices in categories.items():
        if isinstance(data.get(key), str) and data[key] in choices:
            result[key] = data[key]
    for key in ("index", "total", "count", "page", "status_code", "width", "height", "revision"):
        if type(data.get(key)) is int and 0 <= data[key] <= 100000:
            result[key] = data[key]
    for key in ("anonymous", "skipped", "transparent"):
        if type(data.get(key)) is bool:
            result[key] = data[key]
    if value := identifier(data.get("question_id")):
        result["question_id"] = value
    route = data.get("route")
    if isinstance(route, str) and re.fullmatch(
        r"(?:GET|PUT|PATCH|POST|DELETE) /api/[a-z_/{}/.]+", route
    ):
        result["route"] = route[:160]
    # Method names originate in aiogram, but still use an explicit vocabulary.
    if isinstance(data.get("method"), str) and data["method"] in {
        "sendMessage",
        "sendRichMessage",
        "copyMessage",
        "sendPhoto",
        "sendDocument",
        "sendVoice",
        "sendVideo",
        "sendAudio",
        "sendAnimation",
        "sendVideoNote",
        "answerCallbackQuery",
        "editMessageReplyMarkup",
        "editMessageText",
        "deleteMessage",
    }:
        result["method"] = data["method"]
    return result


def usage_event(
    name,
    *,
    source="server",
    user_id=None,
    form_id=None,
    session_id=None,
    at,
    duration_ms=None,
    outcome="ok",
    event_id=None,
    **data,
):
    if name not in SERVER_EVENTS | CLIENT_EVENTS:
        raise ValueError("Unknown analytics event")
    return UsageEvent(
        id=identifier(event_id) or str(uuid4()),
        name=name,
        source=source,
        user_id=user_id
        if type(user_id) is int and user_id > 0 and not data.get("anonymous")
        else None,
        form_id=identifier(form_id),
        session_id=identifier(session_id),
        occurred_at=at,
        duration_ms=max(0, min(86400000, int(duration_ms))) if duration_ms is not None else None,
        outcome=outcome if outcome in {"ok", "rejected", "error"} else "error",
        properties=properties(data),
    )


def record(session, name, *, at, **kwargs):
    """Business milestones join the caller's transaction, including final attendance."""
    session.add(usage_event(name, at=at, **kwargs))
