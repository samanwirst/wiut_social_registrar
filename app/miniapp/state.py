"""Typed keys for per-application services and authenticated request identity."""

from aiogram import Bot
from aiohttp import web

from app.event_repository import EventRepository
from app.services.qr_designer import QrDesigner
from app.services.runtime_health import RuntimeHealth

REPOSITORY = web.AppKey("repository", EventRepository)
BOT = web.AppKey("bot", Bot)
USER = web.RequestKey("user_id", int)
QR_DESIGNER = web.AppKey("qr_designer", QrDesigner)
HEALTH = web.AppKey("runtime_health", RuntimeHealth)
