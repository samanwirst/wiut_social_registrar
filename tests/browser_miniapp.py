"""Optional Chromium integration QA. Run: python tests/browser_miniapp.py.

Requires Playwright and Chromium; uses an isolated temporary database and a fake
bot token. No Telegram messages or Outlook emails are sent.
"""

import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aiogram.types import User
from aiohttp import web
from playwright.async_api import async_playwright

from app.db import Database
from app.event_repository import EventRepository
from app.miniapp import create_web_app
from app.repositories import RegistrationRepository
from registrar.models import Student
from tests.helpers import complete_student_registration, signed_init_data

OUT = Path(tempfile.mkdtemp(prefix="wiut-miniapp-browser-"))
TOKEN = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789"


def contrast(first, second):
    def luminance(rgb):
        values = [component / 255 for component in rgb[:3]]
        linear = [
            value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
            for value in values
        ]
        return sum(value * weight for value, weight in zip(linear, [0.2126, 0.7152, 0.0722]))

    levels = sorted([luminance(first), luminance(second)])
    return (levels[1] + 0.05) / (levels[0] + 0.05)


async def main():
    with TemporaryDirectory() as directory:
        db = Database("sqlite+aiosqlite:///" + directory + "/qa.sqlite3")
        await db.migrate()
        repository = RegistrationRepository(db, "ab" * 32)
        for user_id in [100, *range(1000, 1012)]:
            await repository.touch_user(
                User(id=user_id, is_bot=False, first_name="Student", username=f"student_{user_id}")
            )
            person = Student(
                str(user_id).zfill(8),
                f"Student {user_id}",
                f"student{user_id}@example.test",
                account=f"{user_id}@example.test",
            )
            await complete_student_registration(
                repository, user_id, person, education_level="Level 4", code="123456"
            )
        events = EventRepository(db)
        draft = await events.create(100, "Welcome Night")
        career = await events.create(100, "Career Lab 2026")
        q = {
            "id": str(uuid4()),
            "label": "Which track are you joining?",
            "type": "single_choice",
            "required": True,
            "options": ["Product & design", "Software engineering"],
        }
        career = await events.configure(
            100,
            career.id,
            {
                "title": career.title,
                "description": "Meet the people behind your next opportunity.",
                "registration_open": True,
                "revision": career.revision,
                "response_retention_days": 30,
                "questions": [q],
            },
        )
        for user_id in range(1000, 1012):
            await events.submit_form(
                user_id, career.id, {q["id"]: q["options"][user_id % 2]}, career.revision
            )
        bot = SimpleNamespace(
            token=TOKEN, me=AsyncMock(return_value=SimpleNamespace(username="example_bot"))
        )
        runner = web.AppRunner(create_web_app(events, bot), access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        sdk = """
        const listeners = new Map();
        window.Telegram = {WebApp: {
            initData: __INIT_DATA__, colorScheme: 'light', platform: 'android',
            ready(){}, expand(){}, isVersionAtLeast(){return true;},
            onEvent(name, callback) {
                if (!listeners.has(name)) listeners.set(name, new Set());
                listeners.get(name).add(callback);
            },
            offEvent(name, callback) {listeners.get(name)?.delete(callback);},
            enableClosingConfirmation(){}, disableClosingConfirmation(){},
            BackButton: {show(){}, hide(){}, onClick(callback){window.testBack = callback;}, offClick(){window.testBack = null;}},
            HapticFeedback: {notificationOccurred(){}}
        }};
        window.testTheme = (appearance) => {
            window.Telegram.WebApp.colorScheme = appearance;
            listeners.get('themeChanged')?.forEach(callback => callback());
        };
        """.replace("__INIT_DATA__", json.dumps(signed_init_data()))
        browser_errors = []
        try:
            async with async_playwright() as playwright:
                executable = (
                    os.environ.get("CHROMIUM_EXECUTABLE")
                    or shutil.which("chromium")
                    or shutil.which("chromium-browser")
                )
                browser = await playwright.chromium.launch(
                    executable_path=executable, headless=True
                )
                context = await browser.new_context(viewport={"width": 1280, "height": 1000})
                await context.route(
                    "https://telegram.org/js/telegram-web-app.js",
                    lambda route: route.fulfill(content_type="application/javascript", body=sdk),
                )
                page = await context.new_page()
                page.on("pageerror", lambda error: browser_errors.append(str(error)))
                qr_requests = []
                page.on(
                    "request",
                    lambda request: (
                        qr_requests.append(request.url) if request.url.endswith("/qr") else None
                    ),
                )
                await page.goto(f"http://127.0.0.1:{port}/")
                await page.get_by_role("heading", name="Your events").wait_for()
                await page.screenshot(path=str(OUT / "desktop-events.png"), full_page=True)
                # Reproduce Telegram Desktop's blue night palette, rather than only
                # toggling the library's generic light/dark defaults.
                await page.set_viewport_size({"width": 386, "height": 600})
                await page.evaluate("""() => {
                    const palette = {bg_color:'#17212b', secondary_bg_color:'#232e3c',
                        section_bg_color:'#17212b', text_color:'#f5f5f5', hint_color:'#708499',
                        subtitle_text_color:'#708499', link_color:'#6ab3f3', button_color:'#5288c1',
                        button_text_color:'#ffffff', section_header_text_color:'#6ab3f3'};
                    for (const [key,value] of Object.entries(palette)) {
                        document.documentElement.style.setProperty('--tg-theme-'+key.replaceAll('_','-'), value);
                    }
                    window.testTheme('dark');
                }""")
                assert await page.get_by_role("navigation", name="Pagination").count() == 0
                styles = await page.locator(".event-card").first.evaluate("""node => {
                    const style=getComputedStyle(node);
                    return {background:style.backgroundColor, border:style.borderTopWidth};
                }""")
                assert styles == {"background": "rgba(0, 0, 0, 0)", "border": "0px"}, styles
                colors = await page.locator(".event-meta").first.evaluate("""node => {
                    const canvas=document.createElement('canvas'); canvas.width=canvas.height=1;
                    const context=canvas.getContext('2d');
                    const pixel=color => {context.clearRect(0,0,1,1);context.fillStyle=color;
                        context.fillRect(0,0,1,1);return [...context.getImageData(0,0,1,1).data];};
                    return [pixel(getComputedStyle(node).color), pixel(getComputedStyle(node).getPropertyValue('--tgui--section_bg_color'))];
                }""")
                assert contrast(*colors) >= 4.5, colors
                assert await page.evaluate(
                    "document.documentElement.scrollWidth <= window.innerWidth"
                )
                assert (await page.get_by_role("heading", name="Your events").bounding_box())[
                    "y"
                ] < 45
                await page.screenshot(path=str(OUT / "telegram-desktop-night.png"), full_page=True)
                await page.evaluate("""() => {
                    for (const name of [...document.documentElement.style]) {
                        if (name.startsWith('--tg-theme-')) document.documentElement.style.removeProperty(name);
                    }
                    window.testTheme('light');
                }""")
                await page.set_viewport_size({"width": 1280, "height": 1000})
                await page.get_by_role("button", name="Welcome Night").click()
                await page.get_by_role("heading", name="Welcome Night").wait_for()
                assert await page.locator("#event-qr").count() == 0 and not qr_requests
                await page.get_by_role("tab", name="Questions", exact=True).click()
                assert await page.locator("#event-qr").count() == 0 and not qr_requests
                await page.get_by_role("button", name="+ Add question").click()
                await page.get_by_placeholder("What would you like to ask?").fill(
                    "Which session would you like to join?"
                )
                await page.get_by_label("Answer type").select_option("multiple_choice")
                await page.get_by_label("Option 1", exact=True).fill("Morning")
                await page.get_by_label("Option 2", exact=True).fill("Morning")
                assert await page.get_by_role(
                    "button", name="Remove option 1", exact=True
                ).is_disabled()
                await page.get_by_role("button", name="Save changes", exact=True).click()
                await page.get_by_text("Choice options must be unique.", exact=True).wait_for()
                assert await page.get_by_label("Option 1", exact=True).input_value() == "Morning"
                assert await page.get_by_label("Option 2", exact=True).input_value() == "Morning"
                assert await page.get_by_role(
                    "button", name="Save changes", exact=True
                ).is_enabled()
                await page.get_by_label("Option 2", exact=True).fill("Evening")
                await page.get_by_role("button", name="Add option", exact=True).click()
                assert await page.get_by_label("Option 3", exact=True).evaluate(
                    "input => input === document.activeElement"
                )
                await page.get_by_label("Option 3", exact=True).fill("Temporary")
                await page.get_by_role("button", name="Remove option 2", exact=True).click()
                assert await page.get_by_label("Option 1", exact=True).input_value() == "Morning"
                assert await page.get_by_label("Option 2", exact=True).input_value() == "Temporary"
                assert await page.get_by_label("Option 2", exact=True).evaluate(
                    "input => input === document.activeElement"
                )
                await page.get_by_label("Option 2", exact=True).fill("Evening")
                await page.get_by_label("Option 1", exact=True).press("Enter")
                assert await page.get_by_label("Option 2", exact=True).evaluate(
                    "input => input === document.activeElement"
                )
                await page.get_by_label("Option 2", exact=True).press("Enter")
                assert await page.get_by_label("Option 3", exact=True).evaluate(
                    "input => input === document.activeElement"
                )
                await page.get_by_role("button", name="Remove option 3", exact=True).click()
                await page.get_by_role("button", name="Save changes", exact=True).click()
                await page.get_by_text("All changes saved", exact=True).wait_for()
                event = await events.settings(100, draft.id)
                assert event.questions[0]["options"] == ["Morning", "Evening"]
                assert event.questions[0]["type"] == "multiple_choice"
                await page.screenshot(path=str(OUT / "desktop-questions.png"), full_page=True)
                await page.get_by_role("tab", name="QR", exact=True).click()
                await page.locator("#event-qr").wait_for(state="visible")
                pixels = await page.locator("#event-qr").evaluate("""async image => {
                    await image.decode();
                    const canvas=document.createElement('canvas');
                    canvas.width=image.naturalWidth; canvas.height=image.naturalHeight;
                    const context=canvas.getContext('2d'); context.drawImage(image,0,0);
                    const data=context.getImageData(0,0,canvas.width,canvas.height).data;
                    let opaque=false;
                    for(let i=3;i<data.length;i+=4) if(data[i]===255) {opaque=true;break;}
                    return {cornerAlpha:data[3],hasOpaqueModules:opaque};
                }""")
                assert pixels == {"cornerAlpha": 0, "hasOpaqueModules": True}, pixels
                async with page.expect_download() as exported:
                    await page.get_by_role("button", name="Download PNG", exact=True).click()
                download = await exported.value
                assert download.suggested_filename == f"event-{draft.id}.png"
                await download.save_as(OUT / "event-qr.png")
                assert (OUT / "event-qr.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
                await page.screenshot(path=str(OUT / "desktop-qr.png"), full_page=True)
                await page.get_by_role("tab", name="Questions", exact=True).click()
                assert await page.locator("#event-qr").count() == 0
                assert await page.get_by_label("Option 1", exact=True).input_value() == "Morning"
                assert await page.get_by_label("Option 2", exact=True).input_value() == "Evening"
                await page.get_by_role("button", name="← All events").click()
                await page.get_by_role("button", name="Career Lab 2026").click()
                await page.get_by_role("tab", name="Participants", exact=True).click()
                await page.get_by_text("12 participants · 10 per page", exact=True).wait_for()
                assert (
                    await page.get_by_role("button", name="Delete answers", exact=True).count() == 0
                )
                assert await page.locator("#event-qr").count() == 0
                assert await page.locator("tbody tr").count() == 10
                await page.get_by_role("button", name="Next →", exact=True).click()
                await page.get_by_text("Page 2 of 2", exact=True).wait_for()
                assert await page.locator("tbody tr").count() == 2
                await page.get_by_role("button", name="Refresh", exact=True).click()
                await page.get_by_text("Page 2 of 2", exact=True).wait_for()
                await page.screenshot(path=str(OUT / "desktop-members.png"), full_page=True)
                await page.set_viewport_size({"width": 390, "height": 844})
                for tab_name in ["Overview", "Questions", "Participants", "QR"]:
                    assert await page.get_by_role("tab", name=tab_name, exact=True).is_visible()
                await page.screenshot(path=str(OUT / "mobile-members.png"), full_page=True)
                assert await page.evaluate(
                    "document.documentElement.scrollWidth <= window.innerWidth"
                ), "Page overflows horizontally"
                await page.get_by_role("tab", name="Questions", exact=True).click()
                await page.get_by_text("Question 1 · Locked", exact=True).wait_for()
                assert await page.get_by_label("Question", exact=True).is_disabled()
                assert await page.get_by_label("Option 1", exact=True).is_disabled()
                assert await page.get_by_role("button", name="Add option", exact=True).count() == 0
                await page.screenshot(path=str(OUT / "mobile-questions.png"), full_page=True)
                await page.get_by_role("tab", name="Overview", exact=True).click()
                assert await page.locator("#event-qr").count() == 0
                await page.screenshot(path=str(OUT / "mobile-overview.png"), full_page=True)
                await page.get_by_label("Event name", exact=True).fill("Unsaved name")
                page.once("dialog", lambda dialog: dialog.dismiss())
                await page.get_by_role("button", name="← All events").click()
                assert (
                    await page.get_by_label("Event name", exact=True).input_value()
                    == "Unsaved name"
                )
                page.once("dialog", lambda dialog: dialog.accept())
                await page.get_by_role("button", name="← All events").click()
                await page.get_by_role("heading", name="Your events").wait_for()
                await page.get_by_role("button", name="Career Lab 2026").click()
                assert (
                    await page.get_by_label("Event name", exact=True).input_value()
                    == "Career Lab 2026"
                )
                # Telegram's native BackButton must respect the same unsaved-change guard.
                await page.get_by_label("Event name", exact=True).fill("Keep this draft")
                page.once("dialog", lambda dialog: dialog.dismiss())
                await page.evaluate("window.testBack()")
                assert (
                    await page.get_by_label("Event name", exact=True).input_value()
                    == "Keep this draft"
                )
                page.once("dialog", lambda dialog: dialog.accept())
                await page.evaluate("window.testBack()")
                await page.get_by_role("heading", name="Your events").wait_for()
                await page.get_by_role("button", name="Career Lab 2026").click()
                await page.get_by_label("Event name", exact=True).wait_for()

                light = await page.locator(".event-studio").evaluate(
                    "node => getComputedStyle(node).backgroundColor"
                )
                await page.evaluate("window.testTheme('dark')")
                await page.wait_for_function(
                    "light => getComputedStyle(document.querySelector('.event-studio')).backgroundColor !== light",
                    arg=light,
                )
                await page.screenshot(path=str(OUT / "mobile-dark.png"), full_page=True)
                await page.evaluate("window.testTheme('light')")

                # A separate iOS WebView has visible labels, uses the saved event deep link,
                # and respects both kinds of Telegram safe-area insets.
                ios = await browser.new_context(viewport={"width": 390, "height": 844})
                await ios.route(
                    "https://telegram.org/js/telegram-web-app.js",
                    lambda route: route.fulfill(
                        content_type="application/javascript",
                        body=sdk.replace("platform: 'android'", "platform: 'ios'"),
                    ),
                )
                ios_page = await ios.new_page()
                ios_page.on("pageerror", lambda error: browser_errors.append(str(error)))
                await ios_page.goto(f"http://127.0.0.1:{port}/?event={draft.id}")
                await ios_page.get_by_role("heading", name="Welcome Night").wait_for()
                assert await ios_page.get_by_text("Event name", exact=True).is_visible()
                await ios_page.get_by_role("tab", name="Questions", exact=True).click()
                assert await ios_page.get_by_text("Answer type", exact=True).is_visible()
                assert (
                    await ios_page.get_by_label("Option 1", exact=True).input_value() == "Morning"
                )
                assert (
                    await ios_page.get_by_label("Option 2", exact=True).input_value() == "Evening"
                )
                await ios_page.get_by_role("button", name="Add option", exact=True).click(
                    timeout=5000
                )
                assert await ios_page.get_by_label("Option 3", exact=True).evaluate(
                    "input => input === document.activeElement"
                )
                await ios_page.get_by_role("button", name="Remove option 3", exact=True).click()
                await ios_page.evaluate("""() => {
                    document.documentElement.style.setProperty('--tg-safe-area-inset-top', '12px');
                    document.documentElement.style.setProperty('--tg-content-safe-area-inset-top', '28px');
                }""")
                assert (
                    await ios_page.locator(".event-studio").evaluate(
                        "node => getComputedStyle(node).paddingTop"
                    )
                    == "40px"
                )
                assert await ios_page.evaluate(
                    "document.documentElement.scrollWidth <= window.innerWidth"
                )
                await ios_page.screenshot(path=str(OUT / "ios-questions.png"), full_page=True)
                await browser.close()
            assert not browser_errors, browser_errors
            print(
                "Browser QA passed: separate QR page, lazy loading, transparent PNG download, no delete button, MCQ forms, 10-row pagination, Android/iOS layouts, themes, safe areas and unsaved changes."
            )
            print("Synthetic screenshots:", OUT)
        finally:
            await runner.cleanup()
            await db.close()


asyncio.run(main())
