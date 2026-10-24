from pathlib import Path

from aiohttp import web

from .state import HEALTH

STATIC = Path(__file__).resolve().parents[2] / "frontend" / "dist"
STATIC_FILES = {"index.html", "app.js", "style.css", "style.svg"}
STATIC_DIR = web.AppKey("static_dir", Path)


async def asset(request):
    name = request.match_info.get("name", "index.html")
    if name not in STATIC_FILES:
        raise web.HTTPNotFound()
    return web.FileResponse(
        request.app[STATIC_DIR] / ("assets" if name != "index.html" else "") / name
    )


async def health(request):
    return web.json_response({"status": "ok"})


async def ready(request):
    monitor = request.app.get(HEALTH)
    available = monitor is None or all(
        monitor.components.get(name, {}).get("ok", False) for name in ("database", "polling")
    )
    return web.json_response(
        {"status": "ready" if available else "unavailable"}, status=200 if available else 503
    )
