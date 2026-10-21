from urllib.parse import parse_qsl

from aiogram.utils.web_app import safe_parse_webapp_init_data
from aiohttp import web

from app.clock import utc_now
from app.event_errors import EventError

from .state import BOT, REPOSITORY, USER


def validate_init_data(raw, token, *, now=None):
    """Use aiogram's official Telegram HMAC validation, plus strict parsing and a one-hour TTL."""
    try:
        if not isinstance(raw, str) or not 1 <= len(raw) <= 8192:
            raise ValueError
        pairs = parse_qsl(raw, strict_parsing=True, max_num_fields=32)
        if len({key for key, _ in pairs}) != len(pairs):
            raise ValueError
        data = safe_parse_webapp_init_data(token, raw)
        age = (now or utc_now()).timestamp() - data.auth_date.timestamp()
        if not -30 <= age <= 3600 or data.user is None or data.user.is_bot or data.user.id <= 0:
            raise ValueError
        return data.user.id
    except (ValueError, TypeError, AttributeError, OverflowError):
        raise web.HTTPUnauthorized(
            text="Open the Mini App again from your private chat with the bot."
        ) from None


@web.middleware
async def telegram_auth(request, handler):
    if request.path.startswith("/api/"):
        authorization = request.headers.get("Authorization", "")
        if not authorization.startswith("tma "):
            raise web.HTTPUnauthorized(text="Open this app from Telegram to continue.")
        request[USER] = validate_init_data(authorization[4:], request.app[BOT].token)
        try:
            await request.app[REPOSITORY].require_organizer(request[USER])
        except EventError as error:
            raise web.HTTPForbidden(text=str(error)) from None
    return await handler(request)
