"""Shared parsing for HTTP transport fields."""

from aiohttp import web


async def body(request):
    try:
        data = await request.json()
        if not isinstance(data, dict):
            raise ValueError
        return data
    except (ValueError, UnicodeDecodeError):
        raise web.HTTPBadRequest(text="Submit a JSON object.") from None


def transparent_background(request):
    value = request.query.get("transparent", "true")
    if value not in {"true", "false"}:
        raise web.HTTPBadRequest(text="Transparent must be true or false")
    return value == "true"
