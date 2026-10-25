"""Build the HTTP application; resource ownership stays with the bot runtime."""

from aiohttp import web

from app.broadcasts import BroadcastRepository
from app.events.qr_designs import EventQrDesigns
from app.events.table import EventTable
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
from .state import BOT, BROADCASTS, HEALTH, QR_DESIGNER, REPOSITORY, TABLE
from .table_routes import broadcasts, cancel_broadcast, create_broadcast, edit_cell, table_columns


def create_web_app(repository, bot, *, static_dir=STATIC, qr_designer=None, runtime_health=None):
    app = web.Application(
        middlewares=[errors_and_headers, telegram_auth], client_max_size=128 * 1024
    )
    app[REPOSITORY], app[BOT] = repository, bot
    app[STATIC_DIR] = static_dir
    app[TABLE] = EventTable(repository.db, clock=repository.clock)
    app[BROADCASTS] = BroadcastRepository(repository.db, clock=repository.clock)
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
        ]
    )
    # Both resources share the same signed identity and ownership checks. Keep
    # existing clients/invites working without duplicating transport behavior.
    for resource in ("events", "forms"):
        prefix = "/api/" + resource
        app.add_routes(
            [
                web.get(prefix, list_events),
                web.get(prefix + "/{event_id}", get_event),
                web.put(prefix + "/{event_id}", update_event),
                web.get(prefix + "/{event_id}/members", event_members),
                web.delete(prefix + "/{event_id}/answers", delete_answers),
                web.get(prefix + "/{event_id}/qr", qr_code),
                web.post(prefix + "/{event_id}/qr/designs", create_design),
                web.get(prefix + "/{event_id}/qr/designs", selected_design),
                web.delete(prefix + "/{event_id}/qr/designs", reset_design),
                web.get(prefix + "/{event_id}/qr/designs/{job_id}", design_status),
                web.get(prefix + "/{event_id}/qr/designs/{job_id}/image", design_image),
                web.put(prefix + "/{event_id}/columns", table_columns),
                web.patch(prefix + "/{event_id}/members/{member_id}", edit_cell),
                web.get(prefix + "/{event_id}/broadcasts", broadcasts),
                web.post(prefix + "/{event_id}/broadcasts", create_broadcast),
                web.post(prefix + "/{event_id}/broadcasts/{broadcast_id}/cancel", cancel_broadcast),
            ]
        )
    return app
