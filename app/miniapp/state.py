"""Typed keys for per-application services and authenticated request identity."""

from aiogram import Bot
from aiohttp import web

from app.event_repository import EventRepository

REPOSITORY = web.AppKey("repository", EventRepository)
BOT = web.AppKey("bot", Bot)
USER = web.RequestKey("user_id", int)
