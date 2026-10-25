"""Signed organizer table and audience input/output; persistence owns authorization."""

from aiogram.utils.deep_linking import create_start_link
from aiohttp import web

from .input import body
from .state import BOT, BROADCASTS, TABLE, USER


async def table_columns(request):
    data = await body(request)
    if set(data) != {"columns", "revision"}:
        raise web.HTTPBadRequest(text="Submit columns and their revision")
    return web.json_response(
        await request.app[TABLE].columns(
            request[USER], request.match_info["event_id"], data["columns"], data["revision"]
        )
    )


async def edit_cell(request):
    raw = request.match_info["member_id"]
    if not raw.isascii() or not raw.isdigit() or len(raw) > 19:
        raise web.HTTPBadRequest(text="Invalid person ID")
    if not 0 < int(raw) < 2**63:
        raise web.HTTPBadRequest(text="Invalid person ID")
    return web.json_response(
        await request.app[TABLE].edit(
            request[USER], request.match_info["event_id"], int(raw), await body(request)
        )
    )


async def create_broadcast(request):
    data = await body(request)
    if set(data) != {"recipient_ids", "request_id"}:
        raise web.HTTPBadRequest(text="Submit the selected people and a unique request ID")
    draft = await request.app[BROADCASTS].create(
        request[USER], request.match_info["event_id"], data["recipient_ids"], data["request_id"]
    )
    draft["compose_url"] = await create_start_link(request.app[BOT], "compose_" + draft["id"])
    return web.json_response(draft, status=201)


async def broadcasts(request):
    from .routes import page_number

    status = request.query.get("status")
    if status not in {None, "completed"}:
        raise web.HTTPBadRequest(text="Choose completed messages")
    page = await request.app[BROADCASTS].page(
        request[USER],
        request.match_info["event_id"],
        page_number(request),
        completed_only=status == "completed",
    )
    for item in page["broadcasts"]:
        item["compose_url"] = await create_start_link(request.app[BOT], "compose_" + item["id"])
        item["message_url"] = (
            await create_start_link(request.app[BOT], "message_" + item["id"])
            if item["status"] == "completed"
            else None
        )
    return web.json_response(page)


async def cancel_broadcast(request):
    draft = await request.app[BROADCASTS].get(request[USER], request.match_info["broadcast_id"])
    if draft["event_id"] != request.match_info["event_id"]:
        raise web.HTTPNotFound()
    return web.json_response(await request.app[BROADCASTS].cancel(request[USER], draft["id"]))
