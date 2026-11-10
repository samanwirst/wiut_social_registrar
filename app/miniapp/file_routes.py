"""Signed file-delivery requests; the recipient is always the authenticated owner."""

from uuid import UUID

from aiohttp import web

from app.events.selection import selected_member_ids

from .input import body
from .state import BOT, CHAT_FILES, REPOSITORY, USER


def uuid(value):
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise web.HTTPBadRequest(text="Use a valid file request ID") from None


def delivery_json(job):
    return {"id": job.request_id, "status": job.status, "error": job.error}


async def send_file(request):
    data = await body(request)
    if set(data) - {"member_ids"} != {"request_id", "kind", "transparent", "design_id"}:
        raise web.HTTPBadRequest(text="Submit a file type and unique request ID")
    if data["kind"] not in ("participants", "qr") or type(data["transparent"]) is not bool:
        raise web.HTTPBadRequest(text="Choose a supported file type and background")
    if not isinstance(data["design_id"], str):
        raise web.HTTPBadRequest(text="Choose a valid QR design")
    request_id = uuid(data["request_id"])
    design_id = uuid(data["design_id"]) if data["design_id"] else ""
    if data["kind"] == "participants" and (design_id or data["transparent"] is not True):
        raise web.HTTPBadRequest(text="QR options cannot be used for a participant list")
    member_ids = (
        selected_member_ids(data.get("member_ids")) if data["kind"] == "participants" else None
    )
    if data["kind"] == "qr" and "member_ids" in data:
        raise web.HTTPBadRequest(text="A QR export cannot include a participant selection")
    event = await request.app[REPOSITORY].settings(request[USER], request.match_info["event_id"])
    bot = await request.app[BOT].me()
    job = request.app[CHAT_FILES].submit(
        request[USER],
        event.id,
        request_id,
        data["kind"],
        transparent=data["transparent"],
        design_id=design_id,
        member_ids=member_ids,
    )
    return web.json_response(
        {**delivery_json(job), "chat_url": f"https://t.me/{bot.username}"}, status=202
    )


async def file_status(request):
    event = await request.app[REPOSITORY].settings(request[USER], request.match_info["event_id"])
    job = request.app[CHAT_FILES].get(
        request[USER], event.id, uuid(request.match_info["request_id"])
    )
    if job is None:
        raise web.HTTPNotFound(
            text="This request is no longer available — check your chat before sending again"
        )
    return web.json_response(delivery_json(job))
