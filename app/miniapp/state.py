"""Typed keys for per-application services and authenticated request identity."""

import asyncio

from aiogram import Bot
from aiohttp import web

from app.broadcasts import BroadcastRepository
from app.event_repository import EventRepository
from app.events.table import EventTable
from app.services.qr_designer import QrDesigner
from app.services.runtime_health import RuntimeHealth

REPOSITORY = web.AppKey("repository", EventRepository)
BOT = web.AppKey("bot", Bot)
USER = web.RequestKey("user_id", int)
QR_DESIGNER = web.AppKey("qr_designer", QrDesigner)
HEALTH = web.AppKey("runtime_health", RuntimeHealth)
TABLE = web.AppKey("event_table", EventTable)
BROADCASTS = web.AppKey("broadcasts", BroadcastRepository)
EXPORT_LOCK = web.AppKey("participant_export_lock", asyncio.Lock)
