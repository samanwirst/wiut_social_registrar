"""Private organizer exports; generation never blocks the bot event loop."""

from aiohttp import web

from app.services.participant_export import XLSX_CONTENT_TYPE, prepare_participants

from .state import EXPORT_LOCK, REPOSITORY, USER


async def export_participants(request):
    lock = request.app[EXPORT_LOCK]
    if lock.locked():
        raise web.HTTPTooManyRequests(text="Another export is being prepared — try again shortly")
    event, content = await prepare_participants(
        request.app[REPOSITORY], request[USER], request.match_info["event_id"], lock
    )
    return web.Response(
        body=content,
        content_type=XLSX_CONTENT_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="participants-{event.id}.xlsx"',
        },
    )
