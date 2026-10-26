"""Bounded dependency checks and a heartbeat consumed by an independent watchdog."""

import asyncio
import logging
import time
from uuid import uuid4

from monitoring.state import save_json
from registrar.errors import AuthenticationError, GraphError

logger = logging.getLogger(__name__)
OUTLOOK_TIMEOUT = 25
OUTLOOK_INTERVAL = 300
OUTLOOK_RETRY = 60
DATABASE_INTERVAL = 30


class RuntimeHealth:
    def __init__(self, database, registrar, path, *, clock=time.time):
        self.database, self.registrar, self.path = database, registrar, path
        self.clock = clock
        self.boot_id = str(uuid4())
        self.started_at = clock()
        self.phase = "starting"
        self.components = {}
        self.incidents = {}
        self.tasks = set()
        self.changed = asyncio.Event()
        self.outlook_call = None
        self.outlook_failures = []

    def report(self, component, healthy, reason=""):
        self.components[component] = {"ok": healthy, "reason": reason, "checked_at": self.clock()}
        self.changed.set()

    def incident(self, component, error):
        # Never serialize exception messages, updates, emails, URLs or tracebacks.
        kind = type(error).__name__[:80]
        key = component + ":" + kind
        previous = self.incidents.get(key, {})
        if key not in self.incidents and len(self.incidents) >= 32:
            del self.incidents[min(self.incidents, key=lambda item: self.incidents[item]["at"])]
        self.incidents[key] = {"at": self.clock(), "count": previous.get("count", 0) + 1}
        self.changed.set()

    def snapshot(self):
        return {
            "version": 1,
            "boot_id": self.boot_id,
            "started_at": self.started_at,
            "updated_at": self.clock(),
            "phase": self.phase,
            "components": dict(self.components),
            "incidents": dict(self.incidents),
            "outlook_failures": [dict(failure) for failure in self.outlook_failures],
        }

    def _outlook_result(self, error=None):
        """Keep a bounded outage history after recovery, with fixed diagnostic metadata."""
        previous = self.components.get("outlook", {})
        now = self.clock()
        if error is not None:
            if isinstance(error, AuthenticationError) and not error.network_error:
                reason = "Sign-in required: run cli.py --login on this host"
            elif isinstance(error, GraphError):
                reason = error.diagnostic
            else:
                reason = type(error).__name__
            if not self.outlook_failures or previous.get("ok") is not False:
                self.outlook_failures.append(
                    {
                        "started_at": now,
                        "last_failed_at": now,
                        "reason": reason,
                        "checks_failed": 0,
                        "recovered_at": None,
                    }
                )
                self.outlook_failures = self.outlook_failures[-16:]
            failure = self.outlook_failures[-1]
            failure.update(
                last_failed_at=now, reason=reason, checks_failed=failure["checks_failed"] + 1
            )
            if previous.get("ok") is not False or previous.get("reason") != reason:
                logger.warning("Outlook probe failed (%s)", reason)
            self.report("outlook", False, reason)
        else:
            if previous.get("ok") is False and self.outlook_failures:
                self.outlook_failures[-1]["recovered_at"] = now
                logger.info("Outlook probe recovered")
            self.report("outlook", True)

    async def start(self):
        if self.tasks:
            raise RuntimeError("Runtime health is already running")
        self.phase = "running"
        for coroutine in (self._write(), self._database(), self._outlook()):
            task = asyncio.create_task(coroutine)
            self.tasks.add(task)

    async def _write(self):
        while True:
            self.changed.clear()
            write = asyncio.create_task(asyncio.to_thread(save_json, self.path, self.snapshot()))
            try:
                await asyncio.shield(write)
            except asyncio.CancelledError:
                # A thread cannot be cancelled. Finish this atomic replace before
                # close() writes the final state, so an old heartbeat cannot win.
                await asyncio.gather(write, return_exceptions=True)
                raise
            except OSError as error:
                logger.error("Could not write runtime heartbeat (%s)", type(error).__name__)
            try:
                await asyncio.wait_for(self.changed.wait(), timeout=5)
            except TimeoutError:
                pass

    async def _database(self):
        while True:
            try:
                async with asyncio.timeout(5):
                    await self.database.ping()
                self.report("database", True)
            except Exception as error:
                self.report("database", False, type(error).__name__)
            await asyncio.sleep(DATABASE_INTERVAL)

    async def _outlook(self):
        while True:
            try:
                # A timed-out read stays attached until it finishes. Never enqueue
                # another probe behind an unresolved synchronous worker call.
                if self.outlook_call is None:
                    self.outlook_call = asyncio.create_task(self.registrar.check_connection())
                await asyncio.wait_for(asyncio.shield(self.outlook_call), timeout=OUTLOOK_TIMEOUT)
                self.outlook_call = None
                self._outlook_result()
            except Exception as error:
                if self.outlook_call.done():
                    self.outlook_call = None
                self._outlook_result(error)
            await asyncio.sleep(
                OUTLOOK_RETRY if not self.components["outlook"]["ok"] else OUTLOOK_INTERVAL
            )

    async def polling_request(self, make_request, bot, method):
        if method.__api_method__ != "getUpdates":
            return await make_request(bot, method)
        try:
            result = await make_request(bot, method)
        except Exception as error:
            self.report("polling", False, type(error).__name__)
            raise
        self.report("polling", True)
        return result

    async def close(self):
        if not self.tasks and self.phase != "failed":
            return
        tasks, self.tasks = self.tasks, set()
        if self.outlook_call is not None:
            tasks.add(self.outlook_call)
            self.outlook_call = None
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self.phase != "failed":
            self.phase = "stopped"
        try:
            await asyncio.to_thread(save_json, self.path, self.snapshot())
        except OSError:
            logger.error("Could not save final runtime state")
