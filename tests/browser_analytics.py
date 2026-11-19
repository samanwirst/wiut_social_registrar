"""Real browser + isolated HTTPS/API/DB; all identities and Telegram delivery are synthetic."""

import asyncio
import json
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aiogram.types import User
from aiohttp import web
from playwright.async_api import async_playwright, expect

from app.analytics.auth import AdminAuth, hash_password
from app.analytics.collector import UsageCollector
from app.analytics.events import record
from app.analytics.models import UsageEvent
from app.analytics.queries import AnalyticsQueries
from app.db import Database
from app.event_repository import EventRepository
from app.miniapp import create_web_app
from app.miniapp.analytics_routes import AdminPortal
from app.repositories import RegistrationRepository
from app.surveys import EventSurvey
from tests.helpers import TEST_TOKEN, signed_init_data
from tests.test_event_forms import configuration, question, registered

OUT = Path(tempfile.mkdtemp(prefix="wiut-analytics-browser-"))
PASSWORD = "synthetic browser analytics password"


async def main():
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        # A disposable certificate for this isolated loopback test only.
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                str(root / "key.pem"),
                "-out",
                str(root / "cert.pem"),
                "-days",
                "1",
                "-subj",
                "/CN=localhost",
            ],
            check=True,
            capture_output=True,
        )
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(root / "cert.pem", root / "key.pem")
        db = Database("sqlite+aiosqlite:///" + str(root / "qa.sqlite3"))
        await db.migrate()
        repo = RegistrationRepository(db, "ab" * 32)
        for user_id in range(100, 135):
            await repo.touch_user(User(id=user_id, is_bot=False, first_name="Synthetic student"))
            if user_id < 105:
                await registered(repo, user_id)
        events = EventRepository(db)
        form = await events.create(100, "Campus Volunteers")
        form = await events.configure(
            100,
            form.id,
            configuration(
                form,
                questions=[
                    question(label="What motivates you?"),
                    question("single_choice", label="Your preferred shift"),
                ],
            ),
        )
        await events.visit(101, form.id)
        survey = EventSurvey(events)
        await survey.begin(101, form.id)
        await survey.respond(101, text="A synthetic answer that must never appear in analytics")
        await survey.respond(101, action="choose", option=0)
        await events.visit(102, form.id)
        await survey.begin(102, form.id)
        for index in range(20):
            await events.create(100, f"Campus activity {index + 1}")
        bot = SimpleNamespace(
            token=TEST_TOKEN,
            send_message=AsyncMock(),
            me=AsyncMock(return_value=SimpleNamespace(username="synthetic_bot")),
        )
        collector = UsageCollector(db)
        await collector.start()
        async with db.transaction(write=True) as session:
            for index in range(14):
                record(
                    session,
                    "chat_action",
                    at=repo.clock() - timedelta(days=index),
                    user_id=100 + index % 5,
                    action="start",
                )
            record(
                session,
                "http_request",
                at=repo.clock(),
                user_id=100,
                form_id=form.id,
                route="GET /api/forms/{event_id}/members",
                duration_ms=2300,
                outcome="error",
                error="database",
                status_code=503,
            )
        auth = AdminAuth(
            db, bot, admin_ids=(100,), password_hash=hash_password(PASSWORD), secret="ab" * 32
        )
        portal = AdminPortal(auth, AnalyticsQueries(db, "ab" * 32), "", collector)
        runner = web.AppRunner(
            create_web_app(events, bot, usage_collector=collector, admin_portal=portal),
            access_log=None,
        )
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0, ssl_context=tls)
        await site.start()
        origin = f"https://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
        portal.origin = origin
        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(
                    executable_path=os.environ.get("CHROMIUM_EXECUTABLE")
                    or shutil.which("chromium")
                    or shutil.which("chromium-browser"),
                    args=["--no-sandbox"],
                )
                context = await browser.new_context(
                    ignore_https_errors=True, viewport={"width": 1440, "height": 1000}
                )
                page = await context.new_page()
                failures = []
                page.on("pageerror", lambda error: failures.append(str(error)))
                await page.goto(origin + "/admin")
                await expect(
                    page.get_by_role("heading", name="Administrator sign-in")
                ).to_be_visible()
                await page.get_by_label("Telegram ID").fill("100")
                await page.get_by_label("Password", exact=True).fill(PASSWORD)
                await page.get_by_role("button", name="Send Telegram code").click()
                await expect(
                    page.get_by_role("heading", name="Check your Telegram")
                ).to_be_visible()
                assert bot.send_message.await_count == 1
                code = (
                    bot.send_message.await_args.kwargs["text"]
                    .split("Your one-time code: ")[1]
                    .split("\n")[0]
                )
                await page.get_by_label("Telegram code").fill(
                    f"\u200e{code[:3]} {code[3:]}\u200f\n"
                )
                await expect(page.get_by_label("Telegram code")).to_have_value(code)
                await page.get_by_role("button", name="Open analytics").click()
                await expect(
                    page.get_by_role("heading", name="Your community, in focus")
                ).to_be_visible()
                await expect(page.get_by_text("UX collection started", exact=False)).to_be_visible()
                await page.screenshot(path=str(OUT / "overview-desktop.png"), full_page=True)
                await page.get_by_role("button", name="Registration", exact=True).click()
                await expect(
                    page.get_by_role("heading", name="Registration funnel")
                ).to_be_visible()
                await page.screenshot(path=str(OUT / "registration.png"), full_page=True)
                await page.get_by_role("button", name="Forms", exact=True).click()
                await expect(page.get_by_role("button", name="Next", exact=True)).to_be_enabled()
                await page.get_by_role("button", name="Next", exact=True).click()
                await page.get_by_role("button", name="Campus Volunteers", exact=True).click()
                await expect(
                    page.get_by_role("heading", name="Question-by-question progress")
                ).to_be_visible()
                await expect(page.get_by_text("What motivates you?", exact=False)).to_be_visible()
                assert (
                    "A synthetic answer that must never appear in analytics"
                    not in await page.locator("body").inner_text()
                )
                await page.screenshot(path=str(OUT / "form-detail.png"), full_page=True)
                await page.get_by_role("button", name="Experience", exact=True).click()
                await expect(
                    page.get_by_role("heading", name="Requests and response time")
                ).to_be_visible()
                await page.get_by_role("button", name="Users", exact=True).click()
                await page.locator("td .a-link").first.click()
                await expect(
                    page.get_by_role("heading", name="Journey", exact=False)
                ).to_be_visible()
                await page.get_by_role("button", name="Activity", exact=True).click()
                await page.get_by_label("Outcome", exact=True).select_option("error")
                await expect(page.locator("td .a-badge").first).to_have_text("error")
                await page.reload()
                await expect(
                    page.get_by_role("heading", name="Analytics", exact=True)
                ).to_be_visible()
                await page.set_viewport_size({"width": 390, "height": 844})
                await page.screenshot(path=str(OUT / "overview-phone.png"), full_page=True)
                assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                await page.emulate_media(color_scheme="dark")
                await page.screenshot(path=str(OUT / "overview-phone-dark.png"), full_page=True)
                await page.get_by_role("button", name="Sign out").click()
                await expect(
                    page.get_by_role("heading", name="Administrator sign-in")
                ).to_be_visible()
                assert not failures, failures
                # Exercise actual signed Mini App -> ingestion transport with no real Telegram SDK.
                mini = await context.new_page()
                await mini.add_init_script(
                    """(data => { window.Telegram = { WebApp: { initData: data, platform: 'tdesktop', colorScheme: 'light',
                    ready(){}, expand(){}, isVersionAtLeast(){ return true; }, onEvent(){}, offEvent(){},
                    setHeaderColor(){}, setBackgroundColor(){}, setBottomBarColor(){}, enableClosingConfirmation(){}, disableClosingConfirmation(){},
                    BackButton: {show(){},hide(){},onClick(){},offClick(){}}, HapticFeedback: {notificationOccurred(){}} } }; })("""
                    + json.dumps(signed_init_data())
                    + ");",
                )
                await mini.route(
                    "https://telegram.org/**", lambda route: route.fulfill(status=200, body="")
                )
                await mini.goto(origin + "/?event=" + form.id)
                await mini.get_by_role("tab", name="QR", exact=True).click()
                await mini.get_by_role("button", name="Copy form link").click()
                await mini.wait_for_timeout(3500)
                await collector.flush()
                from sqlalchemy import select

                async with db.transaction() as session:
                    rows = (
                        await session.scalars(
                            select(UsageEvent).where(UsageEvent.source == "miniapp")
                        )
                    ).all()
                    assert any(row.name == "panel_opened" for row in rows)
                    assert any(row.properties.get("screen") == "qr" for row in rows)
                    assert any(row.properties.get("action") == "copy_link" for row in rows)
                await browser.close()
        finally:
            await runner.cleanup()
            await collector.close()
            await db.close()
    print(json.dumps({"status": "passed", "screenshots": str(OUT), "real_external_messages": 0}))


if __name__ == "__main__":
    asyncio.run(main())
