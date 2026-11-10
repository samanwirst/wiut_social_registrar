"""Bounded, owner-scoped file delivery that survives a minimized/disconnected WebView."""

import asyncio
import logging
import time
from dataclasses import dataclass, field

from aiogram.exceptions import TelegramAPIError, TelegramNetworkError, TelegramServerError
from aiogram.types import BufferedInputFile
from aiogram.utils.deep_linking import create_start_link

from app.event_errors import EventError
from app.events.selection import selected_member_ids
from app.services.event_service import event_qr
from app.services.participant_export import prepare_participants

logger = logging.getLogger(__name__)
ACTIVE = {"preparing", "sending"}
TTL = 3600


@dataclass
class FileDelivery:
    owner: int
    event_id: str
    request_id: str
    kind: str
    transparent: bool
    design_id: str
    created_at: float
    member_ids: tuple[int, ...] | None = None
    status: str = "preparing"
    error: str = ""
    task: asyncio.Task | None = field(default=None, repr=False)


class ChatFiles:
    def __init__(self, repository, bot, designer, export_lock, *, clock=time.monotonic):
        self.repository, self.bot, self.designer = repository, bot, designer
        self.export_lock, self.clock = export_lock, clock
        self.jobs = {}
        self.closed = False

    def get(self, owner, event_id, request_id):
        job = self.jobs.get((owner, request_id))
        return job if job is not None and job.event_id == event_id else None

    def submit(
        self, owner, event_id, request_id, kind, *, transparent=True, design_id="", member_ids=None
    ):
        member_ids = selected_member_ids(member_ids) if kind == "participants" else None
        if self.closed:
            raise EventError("File delivery is restarting — please try again shortly")
        self.jobs = {
            key: job
            for key, job in self.jobs.items()
            if job.status in ACTIVE or self.clock() - job.created_at < TTL
        }
        key = owner, request_id
        if previous := self.jobs.get(key):
            if (
                previous.event_id,
                previous.kind,
                previous.transparent,
                previous.design_id,
                previous.member_ids,
            ) != (
                event_id,
                kind,
                transparent,
                design_id,
                member_ids,
            ):
                raise EventError("This file request belongs to another export")
            return previous
        if any(job.owner == owner and job.status in ACTIVE for job in self.jobs.values()):
            raise EventError("Your previous file is still being sent")
        if len(self.jobs) >= 256 or sum(job.status in ACTIVE for job in self.jobs.values()) >= 8:
            raise EventError("File delivery is busy — please try again shortly")
        latest = max(
            (job.created_at for job in self.jobs.values() if job.owner == owner), default=-10
        )
        if self.clock() - latest < 3:
            raise EventError("Please wait a few seconds before sending another file")
        job = FileDelivery(
            owner, event_id, request_id, kind, transparent, design_id, self.clock(), member_ids
        )
        self.jobs[key] = job
        job.task = asyncio.create_task(self._send(job))
        return job

    async def _send(self, job):
        submitted = False
        try:
            async with asyncio.timeout(120):
                if job.kind == "participants":
                    event, content = await prepare_participants(
                        self.repository,
                        job.owner,
                        job.event_id,
                        self.export_lock,
                        member_ids=job.member_ids,
                    )
                    filename = f"participants-{event.id}.xlsx"
                    label = "Participant list"
                else:
                    event = await self.repository.settings(job.owner, job.event_id)
                    if job.design_id:
                        content = await self.designer.image(
                            job.owner, event.id, job.design_id, transparent=job.transparent
                        )
                        if content is None:
                            raise EventError("This QR design is no longer available")
                    else:
                        link = await create_start_link(self.bot, "event_" + event.id)
                        content = await asyncio.to_thread(
                            event_qr, link, transparent=job.transparent
                        )
                    filename = f"event-{event.id}{'-design' if job.design_id else ''}.png"
                    label = (
                        "QR code · "
                        + ("Transparent" if job.transparent else "Opaque")
                        + " background"
                    )
                # All database work and workbook generation finish before network delivery.
                job.status = "sending"
                submitted = True
                await self.bot.send_document(
                    chat_id=job.owner,
                    document=BufferedInputFile(content, filename=filename),
                    caption=f"{event.title}\n{label}",
                    parse_mode=None,
                    request_timeout=45,
                )
                job.status = "sent"
        except asyncio.CancelledError:
            job.error = "Sending was interrupted — check your chat before requesting another file"
            job.status = "unknown" if job.status == "sending" else "failed"
            raise
        except (TelegramNetworkError, TelegramServerError, TimeoutError) as error:
            job.error = (
                "Delivery could not be confirmed — check your chat before requesting another file"
                if job.status == "sending"
                else "Could not prepare this file — please try again later"
            )
            job.status = "unknown" if job.status == "sending" else "failed"
            logger.warning("Chat file delivery unconfirmed (%s)", type(error).__name__)
        except (EventError, TelegramAPIError) as error:
            job.status, job.error = (
                "failed",
                "Could not send this file — return to the panel and try again",
            )
            logger.warning("Chat file delivery rejected (%s)", type(error).__name__)
        except Exception as error:
            job.status, job.error = "failed", "Could not prepare this file — please try again later"
            logger.warning("Chat file preparation failed (%s)", type(error).__name__)
        if job.status == "failed" and not submitted:
            # The panel may already be minimized. Report preparation failures there too.
            try:
                await self.bot.send_message(
                    chat_id=job.owner, text=job.error, parse_mode=None, request_timeout=10
                )
            except Exception as error:
                logger.warning("Chat file failure notice unavailable (%s)", type(error).__name__)

    async def close(self):
        self.closed = True
        tasks = [job.task for job in self.jobs.values() if job.task and not job.task.done()]
        if tasks:
            _, pending = await asyncio.wait(tasks, timeout=50)
            for task in pending:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        self.jobs.clear()
