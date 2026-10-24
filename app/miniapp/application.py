"""Build the HTTP application; resource ownership stays with the bot runtime."""

from aiohttp import web

from app.events.qr_designs import EventQrDesigns
from app.services.qr_designer import QrDesigner

from .assets import STATIC, STATIC_DIR, asset, health, ready
from .auth import telegram_auth
from .middleware import errors_and_headers
from .qr_routes import create_design, design_image, design_status, reset_design, selected_design
from .routes import (
    delete_answers,
    event_members,
    get_event,
    list_events,
    qr_code,
    session_info,
    update_event,
)
from .state import BOT, HEALTH, QR_DESIGNER, REPOSITORY


def create_web_app(repository, bot, *, static_dir=STATIC, qr_designer=None, runtime_health=None):
    app = web.Application(
        middlewares=[errors_and_headers, telegram_auth], client_max_size=128 * 1024
    )
    app[REPOSITORY], app[BOT] = repository, bot
    app[STATIC_DIR] = static_dir
    app[QR_DESIGNER] = qr_designer if qr_designer is not None else QrDesigner()
    if runtime_health is not None:
        app[HEALTH] = runtime_health

    async def designs_lifecycle(app):
        try:
            await app[QR_DESIGNER].start(store=EventQrDesigns(repository.db))
            yield
        finally:
            await app[QR_DESIGNER].close()

    app.cleanup_ctx.append(designs_lifecycle)
    app.add_routes(
        [
            web.get("/health", health),
            web.get("/ready", ready),
            web.get("/", asset),
            web.get("/assets/{name}", asset),
            web.get("/api/session", session_info),
            web.get("/api/events", list_events),
            web.get("/api/events/{event_id}", get_event),
            web.put("/api/events/{event_id}", update_event),
            web.get("/api/events/{event_id}/members", event_members),
            web.delete("/api/events/{event_id}/answers", delete_answers),
            web.get("/api/events/{event_id}/qr", qr_code),
            web.post("/api/events/{event_id}/qr/designs", create_design),
            web.get("/api/events/{event_id}/qr/designs", selected_design),
            web.delete("/api/events/{event_id}/qr/designs", reset_design),
            web.get("/api/events/{event_id}/qr/designs/{job_id}", design_status),
            web.get("/api/events/{event_id}/qr/designs/{job_id}/image", design_image),
        ]
    )
    return app
