import asyncio

from aiogram.utils.deep_linking import create_start_link
from aiohttp import web

from app.services.event_service import event_qr

from .input import body, transparent_background
from .state import BOT, QR_DESIGNER, REPOSITORY, USER


def event_json(event):
    return {
        "id": event.id,
        "title": event.title,
        "description": event.description,
        "registration_open": event.registration_open,
        "questions": event.questions,
        "response_retention_days": event.response_retention_days,
        "revision": event.revision,
        "form_revision": event.form_revision,
        "form_locked": event.form_locked,
        "created_at": event.created_at.isoformat(),
        "department": event.department,
    }


def page_number(request):
    value = request.query.get("page", "0")
    if not value.isascii() or not value.isdigit() or len(value) > 9:
        raise web.HTTPBadRequest(text="Invalid page number.")
    return int(value)


async def session_info(request):
    return web.json_response({"user_id": request[USER]})


async def list_events(request):
    repository = request.app[REPOSITORY]
    page = await repository.owned_events(request[USER], page_number(request))
    counts = page.member_counts
    return web.json_response(
        {
            ("forms" if request.path == "/api/forms" else "events"): [
                {**event_json(event), "members": counts.get(event.id, 0)} for event in page.events
            ],
            "page": page.page,
            "pages": page.pages,
            "total": page.total,
        }
    )


async def get_event(request):
    event = await request.app[REPOSITORY].settings(request[USER], request.match_info["event_id"])
    link = await create_start_link(request.app[BOT], "event_" + event.id)
    return web.json_response(
        {
            **event_json(event),
            "link": link,
            "qr_styling_enabled": request.app[QR_DESIGNER].enabled,
        }
    )


async def update_event(request):
    event = await request.app[REPOSITORY].configure(
        request[USER], request.match_info["event_id"], await body(request)
    )
    return web.json_response(event_json(event))


async def event_members(request):
    page = await request.app[REPOSITORY].answer_page(
        request[USER], request.match_info["event_id"], page_number(request)
    )
    return web.json_response(
        {
            "members": page.members,
            "page": page.page,
            "pages": page.pages,
            "total": page.total,
            "questions": page.event.questions,
            "columns": page.event.table_columns,
            "columns_revision": page.event.columns_revision,
        }
    )


async def delete_answers(request):
    count = await request.app[REPOSITORY].purge_answers(
        request[USER], request.match_info["event_id"]
    )
    return web.json_response({"deleted": count})


async def qr_code(request):
    event = await request.app[REPOSITORY].settings(request[USER], request.match_info["event_id"])
    link = await create_start_link(request.app[BOT], "event_" + event.id)
    png = await asyncio.to_thread(event_qr, link, transparent=transparent_background(request))
    return web.Response(
        body=png,
        content_type="image/png",
        headers={"Content-Disposition": f'attachment; filename="event-{event.id}.png"'},
    )
