"""Authenticated organizer-only QR design transport."""

from aiogram.utils.deep_linking import create_start_link
from aiohttp import web

from .input import body, transparent_background
from .state import BOT, QR_DESIGNER, REPOSITORY, USER


async def create_design(request):
    event = await request.app[REPOSITORY].settings(request[USER], request.match_info["event_id"])
    data = await body(request)
    link = await create_start_link(request.app[BOT], "event_" + event.id)
    designer = request.app[QR_DESIGNER]
    job = designer.submit(request[USER], event.id, link, data.get("prompt"))
    return web.json_response(designer.describe(job), status=202)


async def owned_design(request):
    event = await request.app[REPOSITORY].settings(request[USER], request.match_info["event_id"])
    job = request.app[QR_DESIGNER].get(request[USER], event.id, request.match_info["job_id"])
    return event.id, job


async def selected_design(request):
    event = await request.app[REPOSITORY].settings(request[USER], request.match_info["event_id"])
    return web.json_response(await request.app[QR_DESIGNER].selection(request[USER], event.id))


async def reset_design(request):
    event = await request.app[REPOSITORY].settings(request[USER], request.match_info["event_id"])
    designer = request.app[QR_DESIGNER]
    await designer.reset(request[USER], event.id)
    return web.json_response(await designer.selection(request[USER], event.id))


async def design_status(request):
    event_id, job = await owned_design(request)
    designer = request.app[QR_DESIGNER]
    state = await designer.selection(request[USER], event_id)
    if state["selected"] and state["selected"]["id"] == request.match_info["job_id"]:
        return web.json_response(state["selected"])
    if job is not None:
        return web.json_response(designer.describe(job))
    raise web.HTTPNotFound(text="This design has expired. Please generate a new design")


async def design_image(request):
    event_id, job = await owned_design(request)
    transparent = transparent_background(request)
    image = await request.app[QR_DESIGNER].store.image(
        request[USER], event_id, request.match_info["job_id"], transparent=transparent
    )
    if image is None and job is not None and job.status != "ready":
        raise web.HTTPConflict(text="The design is not ready to download")
    if image is None and job is not None:
        image = job.images[transparent]
    if image is None:
        raise web.HTTPNotFound(text="This design has expired. Please generate a new design")
    return web.Response(
        body=image,
        content_type="image/png",
        headers={"Content-Disposition": f'attachment; filename="event-{event_id}-design.png"'},
    )
