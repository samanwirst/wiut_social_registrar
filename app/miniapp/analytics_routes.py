"""Cookie-authenticated administrator website, separate from signed organizer API access."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from aiohttp import web

from app.analytics.auth import LoginError
from app.analytics.events import CLIENT_EVENTS, SERVER_EVENTS, identifier
from app.analytics.instrumentation import COLLECTOR
from app.analytics.queries import bounded_page, date_range
from app.clock import utc_now

from .assets import STATIC_DIR
from .input import body
from .state import HEALTH, REPOSITORY, USER

SESSION_COOKIE = "__Secure-registrar_admin"
PENDING_COOKIE = "__Secure-registrar_pending"


@dataclass
class AdminPortal:
    auth: object
    queries: object
    origin: str
    collector: object


PORTAL = web.AppKey("admin_portal", AdminPortal)
ADMIN = web.RequestKey("administrator_id", int)


@web.middleware
async def administrator_access(request, handler):
    if request.path == "/admin" or request.path.startswith("/admin/"):
        portal = request.app.get(PORTAL)
        if portal is None:
            raise web.HTTPNotFound()
        if request.method not in {"GET", "HEAD"}:
            if (
                request.headers.get("Origin") != portal.origin
                or request.headers.get("X-Analytics-Request") != "1"
            ):
                raise web.HTTPForbidden(text="Open analytics from its own website")
        if request.path.startswith("/admin/api/") and request.path not in {
            "/admin/api/login",
            "/admin/api/verify",
        }:
            try:
                request[ADMIN] = await portal.auth.authenticate(
                    request.cookies.get(SESSION_COOKIE),
                    csrf=request.headers.get("X-CSRF-Token", "")
                    if request.method not in {"GET", "HEAD"}
                    else None,
                )
            except LoginError as error:
                return web.json_response({"error": str(error)}, status=error.status)
    return await handler(request)


async def admin_page(request):
    return web.FileResponse(request.app[STATIC_DIR] / "admin.html")


async def login(request):
    data = await body(request)
    raw_id, password = data.get("telegram_id"), data.get("password")
    if (
        not isinstance(raw_id, str)
        or not raw_id.isascii()
        or not raw_id.isdigit()
        or not 1 <= len(raw_id) <= 18
        or int(raw_id) <= 0
        or not isinstance(password, str)
        or len(password) > 128
    ):
        raise web.HTTPBadRequest(text="Enter your Telegram ID and password")
    try:
        result, browser = await request.app[PORTAL].auth.request(int(raw_id), password)
    except LoginError as error:
        return web.json_response({"error": str(error)}, status=error.status)
    response = web.json_response(result)
    response.set_cookie(
        PENDING_COOKIE,
        browser,
        max_age=300,
        path="/admin",
        secure=True,
        httponly=True,
        samesite="Strict",
    )
    return response


async def verify(request):
    data = await body(request)
    challenge = identifier(data.get("challenge_id"))
    code = data.get("code")
    if not challenge or not isinstance(code, str) or len(code) > 64:
        raise web.HTTPBadRequest(text="Enter the 6-digit Telegram code")
    try:
        token = await request.app[PORTAL].auth.verify(
            challenge, request.cookies.get(PENDING_COOKIE, ""), code
        )
    except LoginError as error:
        return web.json_response({"error": str(error)}, status=error.status)
    response = web.json_response({"authenticated": True})
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=8 * 3600,
        path="/admin",
        secure=True,
        httponly=True,
        samesite="Strict",
    )
    response.del_cookie(
        PENDING_COOKIE, path="/admin", secure=True, httponly=True, samesite="Strict"
    )
    return response


async def session_info(request):
    return web.json_response(
        {
            "administrator_id": str(request[ADMIN]),
            "csrf": request.app[PORTAL].auth.csrf(request.cookies[SESSION_COOKIE]),
        }
    )


async def logout(request):
    await request.app[PORTAL].auth.logout(request.cookies[SESSION_COOKIE])
    response = web.json_response({"authenticated": False})
    response.del_cookie(
        SESSION_COOKIE, path="/admin", secure=True, httponly=True, samesite="Strict"
    )
    return response


def report_range(request):
    now = utc_now()
    try:
        return date_range(
            request.query.get("start", (now - timedelta(days=29)).date().isoformat()),
            request.query.get("end", now.date().isoformat()),
        )
    except ValueError as error:
        raise web.HTTPBadRequest(text=str(error)) from None


def page_number(request):
    try:
        return bounded_page(request.query.get("page", "0"))
    except ValueError as error:
        raise web.HTTPBadRequest(text=str(error)) from None


async def summary(request):
    portal = request.app[PORTAL]
    result = await portal.queries.summary(*report_range(request))
    result["retention"] = await portal.queries.retention(*report_range(request))
    result["collector"] = portal.collector.status()
    monitor = request.app.get(HEALTH)
    result["runtime"] = (
        [
            {
                "component": component,
                "ok": state["ok"],
                "checked_at": datetime.fromtimestamp(state["checked_at"], timezone.utc).isoformat(),
            }
            for component, state in monitor.components.items()
            if component in {"database", "polling", "outlook", "cleanup"}
        ]
        if monitor
        else []
    )
    return web.json_response(result)


async def forms(request):
    return web.json_response(
        await request.app[PORTAL].queries.forms(*report_range(request), page_number(request))
    )


async def form(request):
    result = await request.app[PORTAL].queries.form(
        request.match_info["form_id"], *report_range(request)
    )
    if result is None:
        raise web.HTTPNotFound()
    return web.json_response(result)


async def users(request):
    return web.json_response(
        await request.app[PORTAL].queries.users(*report_range(request), page_number(request))
    )


async def timeline(request):
    filters = {}
    for key, choices in (
        ("name", SERVER_EVENTS | CLIENT_EVENTS),
        ("outcome", {"ok", "rejected", "error"}),
        ("source", {"bot", "server", "miniapp"}),
    ):
        if value := request.query.get(key):
            if value not in choices:
                raise web.HTTPBadRequest(text="Choose a valid event filter")
            filters[key] = value
    if value := request.query.get("user_id"):
        if not value.isascii() or not value.isdigit() or not 1 <= len(value) <= 18:
            raise web.HTTPBadRequest(text="Choose a valid user")
        filters["user_id"] = int(value)
    return web.json_response(
        await request.app[PORTAL].queries.timeline(
            *report_range(request), page=page_number(request), **filters
        )
    )


async def ingest(request):
    data = await body(request)
    if not identifier(data.get("session_id")):
        raise web.HTTPBadRequest(text="Use a valid interface session")
    collector = request.app.get(COLLECTOR)
    if collector is not None:
        events = data.get("events")
        if (
            not isinstance(events, list)
            or not 1 <= len(events) <= 20
            or any(not isinstance(event, dict) for event in events)
        ):
            raise web.HTTPBadRequest(text="Send between 1 and 20 interface events")
        for form_id in {identifier(event.get("form_id")) for event in events} - {None}:
            await request.app[REPOSITORY].settings(request[USER], form_id)
        try:
            if not collector.client_batch(request[USER], data["session_id"], data.get("events")):
                raise web.HTTPTooManyRequests(text="Interface event limit reached")
        except ValueError as error:
            raise web.HTTPBadRequest(text=str(error)) from None
    return web.Response(status=204)


def install_routes(app, portal=None):
    if portal is not None:
        app[PORTAL] = portal
    app.add_routes(
        [
            web.post("/api/analytics", ingest),
            web.get("/admin", admin_page),
            web.get("/admin/", admin_page),
            web.post("/admin/api/login", login),
            web.post("/admin/api/verify", verify),
            web.get("/admin/api/session", session_info),
            web.post("/admin/api/logout", logout),
            web.get("/admin/api/summary", summary),
            web.get("/admin/api/forms", forms),
            web.get("/admin/api/forms/{form_id}", form),
            web.get("/admin/api/users", users),
            web.get("/admin/api/events", timeline),
        ]
    )
