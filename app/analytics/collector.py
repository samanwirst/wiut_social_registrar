"""Bounded, asynchronous transport telemetry; a telemetry failure never blocks a user action."""

import asyncio
import logging
from collections import OrderedDict, deque
from contextlib import suppress
from datetime import timedelta
from time import monotonic

from sqlalchemy import delete, select

from app.analytics.events import CLIENT_EVENTS, identifier, usage_event
from app.analytics.models import (
    AdminChallenge,
    AdminLoginAttempt,
    AdminSession,
    AnalyticsSetting,
    UsageEvent,
)
from app.clock import utc_now

logger = logging.getLogger(__name__)


class UsageCollector:
    def __init__(self, database, *, clock=utc_now, retention_days=90):
        self.db, self.clock, self.retention_days = database, clock, retention_days
        self.queue = asyncio.Queue(maxsize=2000)
        self.task = None
        self.dropped = 0
        self.failures = 0
        self.last_saved_at = None
        self._clients = OrderedDict()

    def emit(self, name, **data):
        try:
            self.queue.put_nowait(usage_event(name, at=self.clock(), **data))
        except asyncio.QueueFull:
            self.dropped += 1

    def client_batch(self, user_id, session_id, events):
        if not isinstance(events, list) or not 1 <= len(events) <= 20:
            raise ValueError("Send between 1 and 20 events")
        now = monotonic()
        timestamps = self._clients.pop(user_id, deque())
        while timestamps and timestamps[0] <= now - 60:
            timestamps.popleft()
        self._clients[user_id] = timestamps
        if len(self._clients) > 10000:
            self._clients.popitem(last=False)
        if len(timestamps) + len(events) > 120:
            return False
        for event in events:
            if (
                not isinstance(event, dict)
                or not isinstance(event.get("name"), str)
                or event["name"] not in CLIENT_EVENTS
            ):
                raise ValueError("Invalid interface event")
            if "id" in event and identifier(event["id"]) is None:
                raise ValueError("Use a valid interface event ID")
        for event in events:
            timestamps.append(now)
            self.emit(
                event["name"],
                source="miniapp",
                user_id=user_id,
                session_id=session_id,
                event_id=event.get("id"),
                form_id=event.get("form_id"),
                duration_ms=event.get("duration_ms")
                if type(event.get("duration_ms")) is int
                else None,
                **{
                    key: value
                    for key, value in event.items()
                    if key
                    in {"screen", "action", "platform", "width", "height", "page", "count", "error"}
                },
            )
        return True

    async def start(self):
        if self.task is not None:
            raise RuntimeError("Usage collection is already running")
        async with self.db.transaction(write=True) as session:
            for key, value in (("started_at", self.clock().isoformat()), ("auth_lock", "1")):
                await session.execute(
                    self.db.insert(AnalyticsSetting)
                    .values(key=key, value=value)
                    .on_conflict_do_nothing()
                )
        self.task = asyncio.create_task(self._run(), name="product-analytics")

    async def flush(self):
        batch = []
        while len(batch) < 100 and not self.queue.empty():
            batch.append(self.queue.get_nowait())
        if not batch:
            return
        values = [
            {column.name: getattr(event, column.name) for column in UsageEvent.__table__.columns}
            for event in batch
        ]
        try:
            async with asyncio.timeout(5):
                async with self.db.transaction(write=True) as session:
                    await session.execute(
                        self.db.insert(UsageEvent).values(values).on_conflict_do_nothing()
                    )
            self.last_saved_at = self.clock()
        except Exception as error:
            self.failures += 1
            self.dropped += len(batch)
            logger.warning(
                "Usage collection unavailable (%s); %s events dropped",
                type(error).__name__,
                len(batch),
            )
        finally:
            for _ in batch:
                self.queue.task_done()

    async def purge(self):
        now = self.clock()
        async with self.db.transaction(write=True) as session:
            old = (
                select(UsageEvent.id)
                .where(UsageEvent.occurred_at < now - timedelta(days=self.retention_days))
                .limit(5000)
            )
            await session.execute(delete(UsageEvent).where(UsageEvent.id.in_(old)))
            for model in (AdminSession, AdminChallenge):
                await session.execute(delete(model).where(model.expires_at < now))
            await session.execute(
                delete(AdminLoginAttempt).where(
                    AdminLoginAttempt.occurred_at < now - timedelta(days=7)
                )
            )

    async def _run(self):
        last_purge = 0
        while True:
            await asyncio.sleep(1)
            await self.flush()
            if monotonic() - last_purge >= 3600:
                last_purge = monotonic()
                try:
                    await self.purge()
                except Exception as error:
                    logger.warning("Usage retention failed (%s)", type(error).__name__)

    async def close(self):
        if self.task is not None:
            task, self.task = self.task, None
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        # Bounded shutdown; telemetry must not delay draining registrations indefinitely.
        try:
            async with asyncio.timeout(5):
                while not self.queue.empty():
                    await self.flush()
        except TimeoutError:
            self.dropped += self.queue.qsize()

    def status(self):
        return {
            "queued": self.queue.qsize(),
            "dropped": self.dropped,
            "write_failures": self.failures,
            "last_saved_at": self.last_saved_at.isoformat() if self.last_saved_at else None,
            "retention_days": self.retention_days,
        }
