"""Build the HTTP application; resource ownership stays with the bot runtime."""

from aiohttp import web

from .assets import STATIC, STATIC_DIR, asset, health
from .auth import telegram_auth
from .middleware import errors_and_headers
from .routes import (
    delete_answers,
    event_members,
    get_event,
    list_events,
    qr_code,
    session_info,
    update_event,
)
from .state import BOT, REPOSITORY


def create_web_app(repository, bot, *, static_dir=STATIC):
    app = web.Application(
        middlewares=[errors_and_headers, telegram_auth], client_max_size=128 * 1024
    )
    app[REPOSITORY], app[BOT] = repository, bot
    app[STATIC_DIR] = static_dir
    app.add_routes(
        [
            web.get("/health", health),
            web.get("/", asset),
            web.get("/assets/{name}", asset),
            web.get("/api/session", session_info),
            web.get("/api/events", list_events),
            web.get("/api/events/{event_id}", get_event),
            web.put("/api/events/{event_id}", update_event),
            web.get("/api/events/{event_id}/members", event_members),
            web.delete("/api/events/{event_id}/answers", delete_answers),
            web.get("/api/events/{event_id}/qr", qr_code),
        ]
    )
    return app
