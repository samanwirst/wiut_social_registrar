"""Same-origin Telegram Mini App, served alongside the existing bot."""
import asyncio
from contextlib import suppress
from datetime import datetime, timezone
import errno
import logging
from pathlib import Path
import ssl
from urllib.parse import parse_qsl

from aiohttp import web
from aiogram.utils.web_app import safe_parse_webapp_init_data
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.event_repository import EventError
from app.models import EventRegistration
from app.services.event_service import event_qr
from registrar.config import ConfigurationError

logger = logging.getLogger(__name__)
STATIC = Path(__file__).resolve().parents[1] / "frontend" / "dist"
STATIC_FILES = {"index.html", "app.js", "style.css", "style.svg"}
REPOSITORY = web.AppKey("repository", object)
BOT = web.AppKey("bot", object)
USER = web.RequestKey("user_id", int)


def validate_init_data(raw, token, *, now=None):
    """Use aiogram's official Telegram HMAC validation, plus strict parsing and a one-hour TTL."""
    try:
        if not isinstance(raw, str) or not 1 <= len(raw) <= 8192:
            raise ValueError
        pairs = parse_qsl(raw, strict_parsing=True, max_num_fields=32)
        if len({key for key, _ in pairs}) != len(pairs):
            raise ValueError
        data = safe_parse_webapp_init_data(token, raw)
        age = (now or datetime.now(timezone.utc)).timestamp() - data.auth_date.timestamp()
        if not -30 <= age <= 3600 or data.user is None or data.user.is_bot or data.user.id <= 0:
            raise ValueError
        return data.user.id
    except (ValueError, TypeError, AttributeError, OverflowError):
        raise web.HTTPUnauthorized(text="Open the Mini App again from your private chat with the bot.") from None


def event_json(event):
    return {"id": event.id, "title": event.title, "description": event.description,
            "registration_open": event.registration_open, "questions": event.questions,
            "response_retention_days": event.response_retention_days, "revision": event.revision,
            "form_revision": event.form_revision,
            "form_locked": event.form_locked, "created_at": event.created_at.isoformat()}


@web.middleware
async def errors_and_headers(request, handler):
    try:
        response = await handler(request)
    except EventError as error:
        response = web.json_response({"error": str(error)}, status=400)
    except web.HTTPException as error:
        response = web.json_response({"error": error.text if error.status < 500 else "Please try again later."},
                                     status=error.status)
    except (SQLAlchemyError, TelegramAPIError) as error:
        logger.error("Mini App operation failed (%s).", type(error).__name__)
        response = web.json_response({"error": "The service is temporarily unavailable. Please try again."}, status=503)
    response.headers.update({
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
        "Content-Security-Policy": "default-src 'self'; script-src 'self' https://telegram.org; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; connect-src 'self'; "
            "object-src 'none'; base-uri 'none'; form-action 'self'; "
            "frame-ancestors 'self' https://telegram.org https://*.telegram.org",
    })
    return response


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


async def body(request):
    try:
        data = await request.json()
        if not isinstance(data, dict):
            raise ValueError
        return data
    except (ValueError, UnicodeDecodeError):
        raise web.HTTPBadRequest(text="Submit a JSON object.") from None


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
    async with repository.db.transaction() as session:
        rows = (await session.execute(select(EventRegistration.event_id, func.count()).where(
            EventRegistration.event_id.in_([event.id for event in page.events])).group_by(EventRegistration.event_id))).all()
        counts = dict(rows)
    return web.json_response({"events": [{**event_json(event), "members": counts.get(event.id, 0)} for event in page.events],
                              "page": page.page, "pages": page.pages, "total": page.total})


async def get_event(request):
    event = await request.app[REPOSITORY].settings(request[USER], request.match_info["event_id"])
    me = await request.app[BOT].me()
    return web.json_response({**event_json(event), "link": f"https://t.me/{me.username}?start=event_{event.id}"})


async def update_event(request):
    event = await request.app[REPOSITORY].configure(request[USER], request.match_info["event_id"], await body(request))
    return web.json_response(event_json(event))


async def event_members(request):
    page = await request.app[REPOSITORY].answer_page(request[USER], request.match_info["event_id"], page_number(request))
    return web.json_response({"members": page.members, "page": page.page, "pages": page.pages, "total": page.total,
                              "questions": page.event.questions})


async def delete_answers(request):
    count = await request.app[REPOSITORY].purge_answers(request[USER], request.match_info["event_id"])
    return web.json_response({"deleted": count})


async def qr_code(request):
    event = await request.app[REPOSITORY].settings(request[USER], request.match_info["event_id"])
    me = await request.app[BOT].me()
    png = await asyncio.to_thread(event_qr, f"https://t.me/{me.username}?start=event_{event.id}", transparent=True)
    return web.Response(body=png, content_type="image/png",
                        headers={"Content-Disposition": f'attachment; filename="event-{event.id}.png"'})


async def asset(request):
    name = request.match_info.get("name", "index.html")
    if name not in STATIC_FILES:
        raise web.HTTPNotFound()
    return web.FileResponse(STATIC / ("assets" if name != "index.html" else "") / name)


async def health(request):
    return web.json_response({"status": "ok"})


def mini_app_ssl_context(settings):
    if not settings.mini_app_tls_cert_file and not settings.mini_app_tls_key_file:
        return None
    if not settings.mini_app_tls_cert_file or not settings.mini_app_tls_key_file:
        raise ConfigurationError("Direct TLS requires both a certificate and a private key.")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    try:
        # An empty password prevents an encrypted key from opening an interactive prompt.
        context.load_cert_chain(settings.mini_app_tls_cert_file, settings.mini_app_tls_key_file, password="")
    except (OSError, ValueError):
        raise ConfigurationError("Could not load Mini App TLS files. Check the certificate, matching unencrypted key, and file permissions.") from None
    return context


def create_web_app(repository, bot):
    app = web.Application(middlewares=[errors_and_headers, telegram_auth], client_max_size=128 * 1024)
    app[REPOSITORY], app[BOT] = repository, bot
    app.add_routes([
        web.get("/health", health), web.get("/", asset), web.get("/assets/{name}", asset),
        web.get("/api/session", session_info), web.get("/api/events", list_events),
        web.get("/api/events/{event_id}", get_event), web.put("/api/events/{event_id}", update_event),
        web.get("/api/events/{event_id}/members", event_members),
        web.delete("/api/events/{event_id}/answers", delete_answers),
        web.get("/api/events/{event_id}/qr", qr_code),
    ])
    return app


class MiniAppServer:
    def __init__(self, repository, bot, settings):
        self.repository, self.bot, self.settings = repository, bot, settings
        self.runner, self.cleanup_task = None, None

    async def start(self):
        if self.settings.mini_app_url and not (STATIC / "index.html").is_file():
            raise ConfigurationError(
                "Mini App frontend is not built. Run 'npm ci --prefix frontend', "
                "then 'npm run build --prefix frontend', or use the Docker image."
            )
        ssl_context = mini_app_ssl_context(self.settings) if self.settings.mini_app_url else None
        await self.repository.purge_answers()
        self.cleanup_task = asyncio.create_task(self._cleanup(), name="expire-event-answers")
        if self.settings.mini_app_url:
            # Access logs are disabled so that authentication data and survey answers are never logged.
            self.runner = web.AppRunner(create_web_app(self.repository, self.bot), access_log=None)
            await self.runner.setup()
            try:
                await web.TCPSite(self.runner, self.settings.mini_app_host, self.settings.mini_app_port,
                                  ssl_context=ssl_context).start()
            except OSError as error:
                await self.close()
                if error.errno == errno.EADDRINUSE:
                    raise ConfigurationError(
                        f"Mini App port {self.settings.mini_app_port} is already in use. "
                        "Another bot instance or web server may already be running. "
                        "Stop it before starting this instance, or change MINI_APP_PORT and MINI_APP_URL together."
                    ) from None
                raise
            logger.info("Mini App %s server listening on port %s.", "HTTPS" if ssl_context else "HTTP", self.settings.mini_app_port)

    async def _cleanup(self):
        while True:
            await asyncio.sleep(600)
            try:
                await self.repository.purge_answers()
            except SQLAlchemyError as error:
                logger.error("Answer expiration failed (%s); will retry.", type(error).__name__)

    async def close(self):
        if self.cleanup_task is not None:
            self.cleanup_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.cleanup_task
        if self.runner is not None:
            await self.runner.cleanup()
