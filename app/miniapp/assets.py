from pathlib import Path

from aiohttp import web

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
