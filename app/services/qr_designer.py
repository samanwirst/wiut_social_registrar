"""Bounded asynchronous QR design jobs; no SQL, Graph calls, or public image URLs."""

import asyncio
import base64
import binascii
import json
import logging
import math
import time
from dataclasses import dataclass, field
from uuid import uuid4

from aiohttp import ClientError, ClientSession, ClientTimeout

from app.configuration.qr_images import QrImageSettings

from .qr_art import MAX_IMAGE_BYTES, QrDesignError, styled_qr_images

logger = logging.getLogger(__name__)
MODEL = "@cf/black-forest-labs/flux-1-schnell"
MAX_PROMPT = 1200
MAX_JOBS = 12
JOB_TTL = 3600
COOLDOWN = 30


class QrDesignCooldown(QrDesignError):
    def __init__(self, message, retry_after):
        super().__init__(message)
        self.retry_after = max(1, math.ceil(retry_after))


class CloudflareImages:
    def __init__(self, settings: QrImageSettings, session: ClientSession):
        self.settings, self.session = settings, session

    async def generate(self, prompt: str) -> bytes:
        url = f"https://api.cloudflare.com/client/v4/accounts/{self.settings.account_id}/ai/run/{MODEL}"
        try:
            async with self.session.post(
                url,
                headers={"Authorization": "Bearer " + self.settings.api_token},
                json={
                    "prompt": (
                        "Design a distinctive illustrated emblem for an event. "
                        "One bold, recognizable central subject, expressive silhouette, "
                        "cohesive colors, clean shapes with generous white space around it. "
                        "Isolated on a plain white background. Square composition. "
                        "No letters, no text, no QR codes, no watermarks. "
                        "Follow this theme and visual style: " + prompt
                    ),
                    "steps": 4,
                },
                allow_redirects=False,
            ) as response:
                if response.status in (401, 403):
                    raise QrDesignError(
                        "Image generation is not available. Please contact the bot administrator"
                    )
                if response.status == 429:
                    raise QrDesignError(
                        "The image provider is busy or its free quota is used up. Try again later"
                    )
                if response.status != 200:
                    raise QrDesignError(
                        "The image provider could not generate this design. Please try again later"
                    )
                payload = bytearray()
                async for chunk in response.content.iter_chunked(64 * 1024):
                    payload.extend(chunk)
                    if len(payload) > MAX_IMAGE_BYTES * 4 // 3 + 65536:
                        raise QrDesignError("The image provider returned an invalid image")
                data = json.loads(payload)
                if not isinstance(data, dict) or data.get("success") is False:
                    raise ValueError
                encoded = data["result"]["image"]
                if not isinstance(encoded, str):
                    raise ValueError
                image = base64.b64decode(encoded, validate=True)
                if not image or len(image) > MAX_IMAGE_BYTES:
                    raise ValueError
                return image
        except (ClientError, TimeoutError):
            raise QrDesignError(
                "The image provider did not respond in time. Please try again later"
            ) from None
        except (ValueError, KeyError, TypeError, binascii.Error):
            raise QrDesignError("The image provider returned an invalid image") from None


@dataclass
class QrJob:
    owner: int
    event_id: str
    created_at: float
    id: str = field(default_factory=lambda: str(uuid4()))
    status: str = "generating"
    error: str = ""
    images: dict[bool, bytes] = field(default_factory=dict, repr=False)
    task: asyncio.Task | None = field(default=None, repr=False)


class QrDesigner:
    def __init__(self, settings=None, *, provider=None, clock=time.monotonic, health=None):
        self.settings = settings or QrImageSettings()
        self.provider, self.clock = provider, clock
        self.jobs: dict[str, QrJob] = {}
        self.tasks: set[asyncio.Task] = set()
        self.session = None
        self.closed = False
        self.store = None
        self.health = health

    @property
    def enabled(self):
        return bool(self.provider or self.settings.enabled) and not self.closed

    async def start(self, *, store=None):
        self.store = store
        if self.settings.enabled and self.provider is None:
            self.session = ClientSession(timeout=ClientTimeout(total=120, connect=10))
            self.provider = CloudflareImages(self.settings, self.session)

    def _expire(self):
        cutoff = self.clock() - JOB_TTL
        self.jobs = {
            key: job
            for key, job in self.jobs.items()
            if job.created_at >= cutoff or job.status in {"generating", "verifying"}
        }

    def submit(self, owner: int, event_id: str, link: str, prompt: str) -> QrJob:
        if not self.enabled or self.provider is None:
            raise QrDesignError(
                "AI designs are not enabled yet. You can still download the standard QR code"
            )
        if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= MAX_PROMPT:
            raise QrDesignError(f"Describe your design in 1 to {MAX_PROMPT} characters")
        self._expire()
        now = self.clock()
        owned = [job for job in self.jobs.values() if job.owner == owner]
        active = next((job for job in owned if job.status in {"generating", "verifying"}), None)
        if active:
            if active.event_id == event_id:
                return active
            raise QrDesignCooldown("Another design is still being created", 5)
        remaining = self.cooldown(owner)
        if remaining > 0:
            raise QrDesignCooldown("Your next design will be available shortly", remaining)
        if len(self.tasks) >= 2:
            raise QrDesignCooldown("The designer is busy. Please try again shortly", 5)
        if len(self.jobs) >= MAX_JOBS:
            completed = [job for job in self.jobs.values() if job.status in {"ready", "failed"}]
            if completed:
                del self.jobs[min(completed, key=lambda job: job.created_at).id]
        job = QrJob(owner, event_id, now)
        self.jobs[job.id] = job
        task = asyncio.create_task(self._generate(job, link, prompt.strip()))
        job.task = task
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return job

    def get(self, owner: int, event_id: str, job_id: str) -> QrJob | None:
        self._expire()
        job = self.jobs.get(job_id)
        return job if job and job.owner == owner and job.event_id == event_id else None

    def describe(self, job: QrJob):
        elapsed = max(0, self.clock() - job.created_at)
        return {
            "id": job.id,
            "status": job.status,
            "error": job.error,
            "elapsed_seconds": int(elapsed),
            "retry_after": max(0, math.ceil(COOLDOWN - elapsed)),
        }

    def cooldown(self, owner):
        return max(
            0,
            math.ceil(
                max(
                    (
                        COOLDOWN - (self.clock() - job.created_at)
                        for job in self.jobs.values()
                        if job.owner == owner
                    ),
                    default=0,
                )
            ),
        )

    async def selection(self, owner, event_id):
        self._expire()
        active = next(
            (
                job
                for job in self.jobs.values()
                if job.owner == owner
                and job.event_id == event_id
                and job.status in {"generating", "verifying"}
            ),
            None,
        )
        # Capture an active job before the DB await, so a completion during this
        # read cannot leave a reopened panel stuck on the preceding selection.
        selected_id = await self.store.selected(owner, event_id)
        selected = self.get(owner, event_id, selected_id) if selected_id else None
        return {
            "selected": self.describe(selected)
            if selected and selected.status == "ready"
            else (
                {
                    "id": selected_id,
                    "status": "ready",
                    "error": "",
                    "elapsed_seconds": 0,
                    "retry_after": self.cooldown(owner),
                }
                if selected_id
                else None
            ),
            "active": self.describe(active) if active else None,
            "retry_after": self.cooldown(owner),
        }

    async def reset(self, owner, event_id):
        # Await cancellation before deletion: a verification finishing concurrently
        # must not commit a new selected design after the explicit reset.
        tasks = [
            job.task
            for job in self.jobs.values()
            if job.owner == owner
            and job.event_id == event_id
            and job.status in {"generating", "verifying"}
            and job.task is not None
        ]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.store.clear(owner, event_id)

    async def _generate(self, job: QrJob, link: str, prompt: str):
        try:
            async with asyncio.timeout(150):
                artwork = await self.provider.generate(prompt)
                job.status = "verifying"

                # A shared layout must scan in both exports; toggling costs no credits.
                images = await asyncio.to_thread(styled_qr_images, link, artwork)
                if self.store is not None:
                    await self.store.save(job.owner, job.event_id, job.id, images)
                job.images = images
                job.status = "ready"
        except QrDesignError as error:
            if self.health:
                self.health.incident("qr", error)
            job.status, job.error = "failed", str(error)
        except asyncio.CancelledError:
            job.status, job.error = "failed", "The designer restarted. Please generate a new design"
            raise
        except Exception as error:
            logger.warning("QR design failed (%s)", type(error).__name__)
            if self.health:
                self.health.incident("qr", error)
            job.status, job.error = "failed", "Could not finish this design. Please try again later"

    async def close(self):
        self.closed = True
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self.session is not None:
            await self.session.close()
        self.jobs.clear()
