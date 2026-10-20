from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from registrar.auth import TokenProvider
from registrar.config import Settings
from registrar.graph import GraphClient
from registrar.models import Student, validate_student_id


class RegistrarService:
    """Read-only async adapter; one worker owns the Graph session and MSAL cache."""

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
        await self._call(self._client.profile)

    async def find_student(self, student_id: str) -> Student | None:
        student_id = validate_student_id(student_id)
        return await self._call(self._client.find_student, student_id)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            # Queue cleanup after any in-flight synchronous Graph requests.
            await asyncio.get_running_loop().run_in_executor(self._worker, self._client.close)
        finally:
            self._worker.shutdown(wait=False)
