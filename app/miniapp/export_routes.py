"""Private organizer exports; generation never blocks the bot event loop."""

import asyncio

from aiohttp import web

from app.services.participant_export import XLSX_CONTENT_TYPE, participants_xlsx

from .state import EXPORT_LOCK, REPOSITORY, USER


async def export_participants(request):
    lock = request.app[EXPORT_LOCK]
    if lock.locked():
        raise web.HTTPTooManyRequests(text="Another export is being prepared — try again shortly")
    async with lock:
        page = await request.app[REPOSITORY].export_members(
            request[USER], request.match_info["event_id"]
        )
        job = asyncio.create_task(asyncio.to_thread(participants_xlsx, page))
        try:
            content = await asyncio.shield(job)
        except asyncio.CancelledError:
            # Threads cannot be cancelled. Keep the export slot until its writer exits.
            await asyncio.gather(job, return_exceptions=True)
            raise
    return web.Response(
        body=content,
        content_type=XLSX_CONTENT_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="participants-{page.event.id}.xlsx"',
        },
    )
