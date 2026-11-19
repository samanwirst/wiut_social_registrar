"""Transport observations contain categories only, never message bodies or query strings."""

from contextvars import ContextVar
from time import perf_counter

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message
from aiohttp import web
from sqlalchemy.exc import SQLAlchemyError

from app.analytics.events import ACTIONS

CONTEXT = ContextVar("usage_context", default=None)
COLLECTOR = web.AppKey("usage_collector", object)


def error_category(error):
    name = type(error).__name__
    if isinstance(error, (TimeoutError,)):
        return "timeout"
    if isinstance(error, SQLAlchemyError):
        return "database"
    if "Network" in name or "Connection" in name:
        return "network"
    if name.startswith("Telegram"):
        return "rate_limit" if "RetryAfter" in name else "telegram"
    if "Graph" in name or "SendStatus" in name:
        return "outlook"
    if name in {"EventError", "RegistrationError", "ValueError"}:
        return "validation"
    return "internal"


def track(name, **kwargs):
    if context := CONTEXT.get():
        collector, user_id = context
        collector.emit(name, user_id=user_id, **kwargs)


def chat_action(event):
    if isinstance(event, CallbackQuery):
        value = event.data or ""
        if value.startswith("education:"):
            return "education"
        if value.startswith("form:"):
            action = "form_" + value.split(":")[2] if len(value.split(":")) > 2 else ""
            return action if action in ACTIONS else "other_callback"
        if value.startswith("bc:"):
            action = "broadcast_" + value.split(":")[1]
            return action if action in ACTIONS else "other_callback"
        return "other_callback"
    if event.text and event.text.startswith("/"):
        command = event.text.split()[0].split("@")[0][1:]
        return (
            command
            if command
            in {"start", "new_form", "new_event", "panel", "me", "help", "info", "resend", "cancel"}
            else "other_command"
        )
    return (
        "text"
        if event.text
        else "contact"
        if event.contact
        else "attachment"
        if event.content_type != "unknown"
        else "other_message"
    )


class ChatAnalytics(BaseMiddleware):
    def __init__(self, collector):
        self.collector = collector

    async def __call__(self, handler, event, data):
        message = event.message if isinstance(event, CallbackQuery) else event
        if (
            event.from_user is None
            or event.from_user.is_bot
            or not isinstance(message, Message)
            or message.chat.type != "private"
            or message.chat.id != event.from_user.id
        ):
            return await handler(event, data)
        started = perf_counter()
        token = CONTEXT.set((self.collector, event.from_user.id))
        outcome, error = "ok", None
        try:
            return await handler(event, data)
        except Exception as caught:
            outcome, error = "error", error_category(caught)
            raise
        finally:
            entry = None
            if (
                isinstance(event, Message)
                and event.text
                and event.text.split()[0].split("@")[0] == "/start"
            ):
                payload = event.text.split(maxsplit=1)[1] if " " in event.text else ""
                entry = next(
                    (
                        kind
                        for prefix, kind in (
                            ("event_", "invite"),
                            ("compose_", "compose"),
                            ("file_", "file"),
                            ("message_", "message"),
                        )
                        if payload.startswith(prefix)
                    ),
                    "direct",
                )
            self.collector.emit(
                "chat_action",
                source="bot",
                user_id=event.from_user.id,
                action=chat_action(event),
                entry=entry,
                duration_ms=(perf_counter() - started) * 1000,
                outcome=outcome,
                error=error,
            )
            CONTEXT.reset(token)


class TelegramAnalytics:
    def __init__(self, collector):
        self.collector = collector

    async def __call__(self, make_request, bot, method):
        name = method.__api_method__
        if name in {"getUpdates", "getMe", "getWebhookInfo"}:
            return await make_request(bot, method)
        started, outcome, error = perf_counter(), "ok", None
        try:
            return await make_request(bot, method)
        except Exception as caught:
            outcome, error = "error", error_category(caught)
            raise
        finally:
            context = CONTEXT.get()
            self.collector.emit(
                "telegram_request",
                source="bot",
                user_id=context[1] if context else None,
                method=name,
                outcome=outcome,
                error=error,
                duration_ms=(perf_counter() - started) * 1000,
            )


@web.middleware
async def http_analytics(request, handler):
    from app.miniapp.state import USER

    collector = request.app.get(COLLECTOR)
    if (
        collector is None
        or not request.path.startswith("/api/")
        or request.path == "/api/analytics"
    ):
        return await handler(request)
    started = perf_counter()
    token = CONTEXT.set((collector, None))
    try:
        response = await handler(request)
        status = response.status
        resource = request.match_info.route.resource
        route = resource.canonical if resource else "/api/unknown"
        route = route.replace("/api/events", "/api/forms")
        collector.emit(
            "http_request",
            source="server",
            user_id=request.get(USER),
            form_id=request.match_info.get("event_id"),
            route=f"{request.method} {route}",
            status_code=status,
            duration_ms=(perf_counter() - started) * 1000,
            outcome="error" if status >= 500 else "rejected" if status >= 400 else "ok",
            error="internal"
            if status >= 500
            else "authorization"
            if status in {401, 403}
            else "rate_limit"
            if status == 429
            else "validation"
            if status >= 400
            else None,
        )
        return response
    finally:
        CONTEXT.reset(token)
