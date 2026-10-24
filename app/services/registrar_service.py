from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from registrar.auth import TokenProvider
from registrar.config import Settings
from registrar.graph import GraphClient
from registrar.models import Student, validate_student_id

PRODUCTION_BOT_USERNAME = "social_registrar_bot"


class RegistrarService:
    """One worker owns the Graph session and MSAL cache."""

    def __init__(self, settings: Settings):
        auth = TokenProvider(settings, status=lambda _: None, interactive=False)
        self._client = GraphClient(settings, auth=auth)
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="outlook")
        self._closed = False

    async def _call(self, function, *args):
        if self._closed:
            raise RuntimeError("The registrar service is closed.")
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._worker, partial(function, *args))

    async def check_connection(self) -> None:
        # A health probe must reach Graph even when sender identity is cached.
        await self._call(partial(self._client.profile, refresh=True))

    async def find_student(self, student_id: str, *, refresh: bool = False) -> Student | None:
        student_id = validate_student_id(student_id)
        return await self._call(partial(self._client.find_student, refresh=refresh), student_id)

    async def send_verification_code(self, student: Student, code: str, ttl_seconds: int) -> None:
        # Only this fixed template is exposed to the bot; callers cannot supply mail content.
        body = (
            f"Your Social Registrar verification code is:\n\n{code}\n\n"
            f"This code expires in {ttl_seconds // 60} minutes and can only be used once\n"
            "Enter the code in: "
            f"https://t.me/{PRODUCTION_BOT_USERNAME}\n\n"
            "If you did not request this code, you can ignore this email\n"
            "Do not share this code with anyone!"
        )
        await self._call(
            self._client.send_email, student, "WIUT Social Registrar verification code", body
        )

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            # Queue cleanup after any in-flight synchronous Graph requests.
            await asyncio.get_running_loop().run_in_executor(self._worker, self._client.close)
        finally:
            self._worker.shutdown(wait=False)
