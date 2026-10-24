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
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from io import BytesIO

from aiogram.types import User
from aiohttp import web
from PIL import Image, ImageDraw
from playwright.async_api import async_playwright

from app.db import Database
from app.event_repository import EventRepository
from app.miniapp import create_web_app
from app.repositories import RegistrationRepository
from app.services.qr_art import QrDesignError, scan_verified
from app.services.qr_designer import QrDesigner
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


async def assert_native_geometry(page, platform):
    geometry = await page.evaluate("""() => {
        const visible = node => node.getClientRects().length > 0;
        const styles = selector => [...document.querySelectorAll(selector)].filter(visible)
            .map(node => ({radius: getComputedStyle(node).borderTopLeftRadius,
                height: node.getBoundingClientRect().height}));
        return {
            sections: styles('.studio-section > div > div'),
            controls: styles('.field > div > label, .poll-option-row > div > label'),
            buttons: styles('.event-studio button:not([role=tab]):not(.event-card):not(.poll-option-remove)'),
            arrows: [...document.querySelectorAll('.event-studio button')]
                .filter(node => /[←→↑↓›＋]/u.test(node.textContent)).map(node => node.textContent),
            overflow: document.documentElement.scrollWidth > window.innerWidth,
            chrome: [window.testHeaderColor, window.testBackgroundColor, window.testBottomBarColor],
        };
    }""")
    assert not geometry["overflow"], geometry
    assert not geometry["arrows"], geometry
    assert geometry["chrome"] == ["secondary_bg_color"] * 3, geometry
    assert all(item["radius"] == "12px" for item in geometry["sections"]), geometry
    radius = "12px" if platform == "ios" else "8px"
    assert all(item["radius"] == radius for item in geometry["controls"]), geometry
    assert all(item["radius"] == radius for item in geometry["buttons"]), geometry
    assert all(item["height"] >= 44 for item in geometry["buttons"]), geometry
    assert all(item["height"] >= 48 for item in geometry["controls"]), geometry


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
        art = Image.new("RGB", (1024, 1024), "#244d25")
        draw = ImageDraw.Draw(art)
        for y in range(0, 1024, 64):
            for x in range(0, 1024, 64):
                draw.rectangle(
                    (x, y, x + 63, y + 63), fill=(20 + x % 180, 70 + y % 150, 35 + (x + y) % 80)
                )
        image_buffer = BytesIO()
        art.save(image_buffer, format="PNG")
        provider = SimpleNamespace(generate=AsyncMock(return_value=image_buffer.getvalue()))
        qr_clock_offset = [0]
        qr_designer = QrDesigner(
            provider=provider, clock=lambda: time.monotonic() + qr_clock_offset[0]
        )
        runner = web.AppRunner(
            create_web_app(events, bot, qr_designer=qr_designer), access_log=None
        )
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        sdk = """
        const listeners = new Map();
        window.Telegram = {WebApp: {
            initData: __INIT_DATA__, colorScheme: 'light', platform: 'android',
            ready(){}, expand(){}, isVersionAtLeast(){return true;},
            setHeaderColor(color){window.testHeaderColor=color;},
            setBackgroundColor(color){window.testBackgroundColor=color;},
            setBottomBarColor(color){window.testBottomBarColor=color;},
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
                        qr_requests.append(request.url)
                        if request.url.split("?")[0].endswith("/qr")
                        else None
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
                await assert_native_geometry(page, "base")
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
                await page.get_by_role("tab", name="Overview", exact=True).focus()
                await page.keyboard.press("ArrowRight")
                assert (
                    await page.get_by_role("tab", name="Questions", exact=True).get_attribute(
                        "aria-selected"
                    )
                    == "true"
                )
                await page.keyboard.press("ArrowLeft")
                assert (
                    await page.get_by_role("tab", name="Overview", exact=True).get_attribute(
                        "aria-selected"
                    )
                    == "true"
                )
                await page.get_by_role("tab", name="Questions", exact=True).click()
                assert await page.locator("#event-qr").count() == 0 and not qr_requests
                await page.get_by_role("button", name="Add question").click()
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
                await page.locator(".studio-snackbar").evaluate(
                    "node => Promise.all(node.getAnimations().map(animation => animation.finished))"
                )
                toast = await page.locator(".studio-snackbar").bounding_box()
                savebar = await page.locator(".savebar").bounding_box()
                assert toast is not None and savebar is not None
                assert (
                    toast["y"] + toast["height"] <= savebar["y"]
                    or savebar["y"] + savebar["height"] <= toast["y"]
                ), (toast, savebar)
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
                await page.locator(".qr-background").click()
                assert not await page.get_by_label(
                    "Transparent background", exact=True
                ).is_checked()
                await page.get_by_text("PNG · Opaque background", exact=True).wait_for()
                await page.locator("#event-qr").wait_for()
                await page.get_by_label("Design prompt").fill(
                    "Warm autumn colors and soft natural textures"
                )
                assert (
                    await page.get_by_label("Design prompt").get_attribute("placeholder")
                    == "Describe the theme, colors, and style you have in mind"
                )
                artwork_entered, release_artwork = asyncio.Event(), asyncio.Event()

                async def slow_artwork(_):
                    artwork_entered.set()
                    await asyncio.wait_for(release_artwork.wait(), timeout=40)
                    return image_buffer.getvalue()

                provider.generate.side_effect = slow_artwork
                submitted, release_submission = asyncio.Event(), asyncio.Event()

                async def slow_submission(route):
                    response = await route.fetch()
                    submitted.set()
                    await asyncio.wait_for(release_submission.wait(), timeout=10)
                    await route.fulfill(response=response)

                await page.route("**/qr/designs", slow_submission)
                await page.get_by_role("button", name="Generate design", exact=True).click()
                await asyncio.wait_for(submitted.wait(), timeout=5)
                await page.get_by_text("Sending your request", exact=True).wait_for()
                assert (
                    await page.get_by_role("button", name="Download PNG", exact=True).count() == 0
                )
                # Switching tabs never cancels the server job. The job is resumed by ID.
                await page.get_by_role("tab", name="Questions", exact=True).click()
                await page.get_by_role("tab", name="QR", exact=True).click()
                release_submission.set()
                await asyncio.wait_for(artwork_entered.wait(), timeout=5)
                await page.get_by_text("Creating your image", exact=True).wait_for()
                await page.locator(".qr-result").screenshot(path=str(OUT / "qr-generating.png"))
                await page.set_viewport_size({"width": 390, "height": 760})
                for appearance in ("light", "dark"):
                    await page.evaluate("mode => window.testTheme(mode)", appearance)
                    await page.locator(".qr-result").scroll_into_view_if_needed()
                    await page.screenshot(path=str(OUT / f"qr-generating-{appearance}-mobile.png"))
                    assert not await page.evaluate(
                        "document.documentElement.scrollWidth > innerWidth"
                    )
                await page.emulate_media(reduced_motion="reduce")
                assert (
                    await page.locator(".qr-generation-canvas").evaluate(
                        "node => getComputedStyle(node, '::before').animationName"
                    )
                    == "none"
                )
                await page.emulate_media(reduced_motion="no-preference")
                await page.set_viewport_size({"width": 1280, "height": 1000})
                await page.evaluate("window.testTheme('light')")
                assert (
                    await page.locator(".qr-generation-stages [aria-current=step]").inner_text()
                    == "Create artwork"
                )

                async def lost_status(route):
                    await route.fulfill(status=503, json={"error": "Connection interrupted"})

                await page.route("**/qr/designs/*", lost_status)
                await page.get_by_role("button", name="Reconnect", exact=True).wait_for()
                await page.get_by_text("Connection interrupted", exact=True).wait_for()
                assert provider.generate.await_count == 1
                await page.unroute("**/qr/designs/*", lost_status)
                await page.get_by_role("button", name="Reconnect", exact=True).click()
                await page.get_by_text("Creating your image", exact=True).wait_for()

                verifying_shown = [False]

                async def expose_verification(route):
                    response = await route.fetch()
                    data = await response.json()
                    if data.get("status") == "ready" and not verifying_shown[0]:
                        verifying_shown[0] = True
                        data["status"] = "verifying"
                    await route.fulfill(response=response, json=data)

                await page.route("**/qr/designs/*", expose_verification)
                release_artwork.set()
                await page.get_by_text("Checking QR readability", exact=True).wait_for()
                await page.locator(".qr-result").screenshot(path=str(OUT / "qr-verifying.png"))
                assert (
                    await page.locator(".qr-generation-stages [aria-current=step]").inner_text()
                    == "Check QR"
                )
                assert (
                    await page.get_by_role("button", name="Download PNG", exact=True).count() == 0
                )
                await page.get_by_text(
                    "PNG · Opaque background · Scan checked", exact=True
                ).wait_for()
                await page.unroute("**/qr/designs/*", expose_verification)
                assert await page.get_by_role("button", name="Reconnect", exact=True).count() == 0
                assert (
                    await page.get_by_role("button", name="Check status", exact=True).count() == 0
                )
                assert await page.get_by_role(
                    "button", name="Generate again in", exact=False
                ).is_disabled()
                assert (
                    await page.get_by_label("Design prompt").input_value()
                    == "Warm autumn colors and soft natural textures"
                )
                await page.locator(".qr-background").click()
                await page.get_by_text(
                    "PNG · Transparent background · Scan checked", exact=True
                ).wait_for()
                await page.locator("#event-qr").wait_for()
                assert provider.generate.await_count == 1
                await page.unroute("**/qr/designs", slow_submission)
                async with page.expect_download() as styled_export:
                    await page.get_by_role("button", name="Download PNG", exact=True).click()
                styled_download = await styled_export.value
                assert styled_download.suggested_filename == f"event-{draft.id}-design.png"
                await styled_download.save_as(OUT / "event-qr-design-transparent.png")
                with Image.open(OUT / "event-qr-design-transparent.png") as exported_image:
                    assert exported_image.mode == "RGBA"
                    assert scan_verified(
                        exported_image, f"https://t.me/example_bot?start=event_{draft.id}"
                    )
                await page.locator(".qr-background").click()
                assert not await page.get_by_label(
                    "Transparent background", exact=True
                ).is_checked()
                await page.get_by_text(
                    "PNG · Opaque background · Scan checked", exact=True
                ).wait_for()
                await page.locator("#event-qr").wait_for()
                async with page.expect_download() as opaque_export:
                    await page.get_by_role("button", name="Download PNG", exact=True).click()
                await (await opaque_export.value).save_as(OUT / "event-qr-design-opaque.png")
                with Image.open(OUT / "event-qr-design-opaque.png") as exported_image:
                    assert exported_image.mode == "RGB"
                    assert scan_verified(
                        exported_image, f"https://t.me/example_bot?start=event_{draft.id}"
                    )
                assert provider.generate.await_count == 1
                await page.screenshot(path=str(OUT / "desktop-qr-design.png"), full_page=True)
                # Telegram can reopen a Mini App in a completely fresh WebView.
                # The server selection restores the exact bytes, without relying
                # on either browser storage or a fresh provider request.
                fresh = await browser.new_context(viewport={"width": 390, "height": 844})
                await fresh.route(
                    "https://telegram.org/js/telegram-web-app.js",
                    lambda route: route.fulfill(content_type="application/javascript", body=sdk),
                )
                reopened = await fresh.new_page()
                standard_requests = []
                reopened.on(
                    "request",
                    lambda request: (
                        standard_requests.append(request.url)
                        if request.url.split("?")[0].endswith("/qr")
                        else None
                    ),
                )

                async def lost_selection(route):
                    await route.fulfill(status=503, json={"error": "Connection interrupted"})

                await reopened.route("**/qr/designs", lost_selection)
                await reopened.goto(f"http://127.0.0.1:{port}/?event={draft.id}")
                await reopened.get_by_role("tab", name="QR", exact=True).click()
                await reopened.get_by_text("Connection interrupted", exact=True).wait_for()
                assert await reopened.locator("#event-qr").count() == 0
                assert not standard_requests
                await reopened.unroute("**/qr/designs", lost_selection)
                await reopened.get_by_role("button", name="Reconnect", exact=True).click()
                await reopened.get_by_text(
                    "PNG · Transparent background · Scan checked", exact=True
                ).wait_for()
                await reopened.locator("#event-qr").wait_for()
                async with reopened.expect_download() as fresh_export:
                    await reopened.get_by_role("button", name="Download PNG", exact=True).click()
                await (await fresh_export.value).save_as(OUT / "event-qr-reopened.png")
                assert (OUT / "event-qr-reopened.png").read_bytes() == (
                    OUT / "event-qr-design-transparent.png"
                ).read_bytes()
                assert not standard_requests and provider.generate.await_count == 1
                await reopened.screenshot(path=str(OUT / "qr-reopened-mobile.png"), full_page=True)
                await fresh.close()
                # Reopen a ready job after its cooldown, then verify failed regeneration
                # preserves the checked PNG instead of silently replacing it with a plain QR.
                qr_clock_offset[0] += 31
                await page.goto(f"http://127.0.0.1:{port}/?event={draft.id}")
                await page.get_by_role("tab", name="QR", exact=True).click()
                await page.get_by_text(
                    "PNG · Opaque background · Scan checked", exact=True
                ).wait_for()
                assert not await page.get_by_label(
                    "Transparent background", exact=True
                ).is_checked()
                await page.locator("#event-qr").wait_for()
                previous_preview = await page.locator("#event-qr").get_attribute("src")
                provider.generate.side_effect = QrDesignError(
                    "The image provider is busy — try again later"
                )
                await page.get_by_label("Design prompt").fill(
                    "Cool blue colors and abstract shapes"
                )
                await page.get_by_role("button", name="Generate design", exact=True).click()
                await page.get_by_text("Couldn't create this design", exact=True).wait_for()
                assert await page.locator("#event-qr").get_attribute("src") == previous_preview
                assert await page.get_by_role(
                    "button", name="Download PNG", exact=True
                ).is_enabled()
                assert await page.get_by_role("button", name="Reconnect", exact=True).count() == 0
                await page.locator(".qr-result").screenshot(
                    path=str(OUT / "qr-generation-failed.png")
                )
                await page.get_by_role("button", name="Use standard QR", exact=True).click()
                await page.get_by_text("PNG · Opaque background", exact=True).wait_for()
                qr_clock_offset[0] += 31
                await page.goto(f"http://127.0.0.1:{port}/?event={draft.id}")
                await page.get_by_role("tab", name="QR", exact=True).click()
                await page.locator("#event-qr").wait_for()

                async def quota_wait(route):
                    await route.fulfill(
                        status=429,
                        headers={"Retry-After": "2"},
                        json={
                            "error": "Your next design will be available shortly",
                            "retry_after": 2,
                        },
                    )

                await page.route("**/qr/designs", quota_wait)
                await page.get_by_label("Design prompt").fill("Simple shapes and warm colors")
                await page.get_by_role("button", name="Generate design", exact=True).click()
                await page.get_by_role("button", name="Generate again in", exact=False).wait_for()
                assert await page.get_by_role(
                    "button", name="Generate again in", exact=False
                ).is_disabled()
                assert await page.get_by_role("alert").count() == 0
                assert (
                    await page.get_by_role("button", name="Check status", exact=True).count() == 0
                )
                assert await page.get_by_role("button", name="Reconnect", exact=True).count() == 0
                await page.get_by_role("button", name="Generate design", exact=True).wait_for()
                assert await page.get_by_role(
                    "button", name="Generate design", exact=True
                ).is_enabled()
                assert provider.generate.await_count == 2
                await page.unroute("**/qr/designs", quota_wait)

                # Expiration is recoverable, rather than an endless generating state.
                stale_once = [True]

                async def expired_active_job(route):
                    if stale_once[0]:
                        stale_once[0] = False
                        await route.fulfill(
                            json={
                                "selected": None,
                                "active": {
                                    "id": "expired-preview",
                                    "status": "generating",
                                    "error": "",
                                    "elapsed_seconds": 0,
                                    "retry_after": 0,
                                },
                                "retry_after": 0,
                            }
                        )
                    else:
                        await route.continue_()

                await page.route("**/qr/designs", expired_active_job)
                await page.goto(f"http://127.0.0.1:{port}/?event={draft.id}")
                await page.get_by_role("tab", name="QR", exact=True).click()
                await page.get_by_text(
                    "This preview has expired — generate a new design when you are ready",
                    exact=True,
                ).wait_for()
                await page.locator("#event-qr").wait_for()
                assert await page.get_by_role("button", name="Reconnect", exact=True).count() == 0
                assert await page.get_by_role("alert").count() == 0
                await page.unroute("**/qr/designs", expired_active_job)
                await page.get_by_role("tab", name="Questions", exact=True).click()
                assert await page.locator("#event-qr").count() == 0
                assert await page.get_by_label("Option 1", exact=True).input_value() == "Morning"
                assert await page.get_by_label("Option 2", exact=True).input_value() == "Evening"
                await page.get_by_role("button", name="All events").click()
                await page.get_by_role("button", name="Career Lab 2026").click()
                await page.get_by_role("tab", name="Participants", exact=True).click()
                await page.get_by_text("12 participants · 10 per page", exact=True).wait_for()
                assert (
                    await page.get_by_role("button", name="Delete answers", exact=True).count() == 0
                )
                assert await page.locator("#event-qr").count() == 0
                assert await page.locator("tbody tr").count() == 10
                await page.get_by_role("button", name="Next", exact=True).click()
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
                await page.get_by_role("button", name="All events").click()
                assert (
                    await page.get_by_label("Event name", exact=True).input_value()
                    == "Unsaved name"
                )
                page.once("dialog", lambda dialog: dialog.accept())
                await page.get_by_role("button", name="All events").click()
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
                await ios_page.evaluate("""() => {
                    document.documentElement.style.setProperty('--tg-safe-area-inset-bottom', '12px');
                    document.documentElement.style.setProperty('--tg-content-safe-area-inset-bottom', '20px');
                }""")
                assert (
                    await ios_page.locator(".savebar").evaluate(
                        "node => getComputedStyle(node).bottom"
                    )
                    == "44px"
                )
                await ios_page.screenshot(path=str(OUT / "ios-questions.png"), full_page=True)

                # Review the same surfaces and geometry in both platform variants,
                # appearances and narrow/wide Telegram windows. All data is synthetic.
                for platform, visual in [("base", page), ("ios", ios_page)]:
                    for appearance in ("light", "dark"):
                        for view, event_id, tab in [
                            ("events", None, None),
                            ("overview", draft.id, "Overview"),
                            ("questions", draft.id, "Questions"),
                            ("participants", career.id, "Participants"),
                            ("qr", draft.id, "QR"),
                        ]:
                            await visual.set_viewport_size({"width": 390, "height": 844})
                            suffix = f"?event={event_id}" if event_id else ""
                            await visual.goto(f"http://127.0.0.1:{port}/{suffix}")
                            title = (
                                "Your events"
                                if event_id is None
                                else (
                                    "Career Lab 2026" if event_id == career.id else "Welcome Night"
                                )
                            )
                            await visual.get_by_role("heading", name=title, exact=True).wait_for()
                            await visual.evaluate("mode => window.testTheme(mode)", appearance)
                            if platform == "base" and appearance == "dark":
                                await visual.evaluate("""() => {
                                    const palette = {bg_color:'#17212b', secondary_bg_color:'#232e3c',
                                        section_bg_color:'#17212b', text_color:'#f5f5f5', hint_color:'#708499',
                                        subtitle_text_color:'#708499', link_color:'#6ab3f3', button_color:'#5288c1',
                                        button_text_color:'#ffffff', section_header_text_color:'#6ab3f3'};
                                    for (const [key,value] of Object.entries(palette)) {
                                        document.documentElement.style.setProperty('--tg-theme-'+key.replaceAll('_','-'), value);
                                    }
                                }""")
                            if tab:
                                await visual.get_by_role("tab", name=tab, exact=True).click()
                                assert (
                                    await visual.get_by_role(
                                        "tab", name=tab, exact=True
                                    ).get_attribute("aria-selected")
                                    == "true"
                                )
                            if view == "participants":
                                await visual.get_by_text(
                                    "12 participants · 10 per page", exact=True
                                ).wait_for()
                                await visual.locator("tbody tr").first.wait_for()
                            if view == "qr":
                                await visual.locator("#event-qr").wait_for()
                                await visual.locator("#event-qr").evaluate(
                                    "image => image.decode()"
                                )
                            await visual.mouse.move(0, 0)
                            if tab:
                                await visual.locator(".tabs").evaluate(
                                    "node => Promise.all(node.getAnimations({subtree:true}).map(animation => animation.finished.catch(() => {})))"
                                )
                            await visual.evaluate(
                                "() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))"
                            )
                            await assert_native_geometry(visual, platform)
                            await visual.screenshot(
                                path=str(OUT / f"native-{platform}-{appearance}-{view}.png"),
                                full_page=True,
                                animations="disabled",
                            )
                            if view == "questions":
                                add_question = visual.get_by_role(
                                    "button", name="Add question", exact=True
                                )
                                await add_question.scroll_into_view_if_needed()
                                action = await add_question.bounding_box()
                                bar = await visual.locator(".savebar").bounding_box()
                                assert action is not None and bar is not None
                                assert action["y"] + action["height"] <= bar["y"], (action, bar)
                                await visual.screenshot(
                                    path=str(
                                        OUT / f"native-{platform}-{appearance}-question-actions.png"
                                    ),
                                    animations="disabled",
                                )
                            for width in (320, 900):
                                await visual.set_viewport_size({"width": width, "height": 844})
                                await assert_native_geometry(visual, platform)
                # Older clients keep their supported native colors and skip 7.10 methods.
                legacy = await browser.new_context(viewport={"width": 390, "height": 844})
                await legacy.route(
                    "https://telegram.org/js/telegram-web-app.js",
                    lambda route: route.fulfill(
                        content_type="application/javascript",
                        body=sdk.replace(
                            "isVersionAtLeast(){return true;}",
                            "isVersionAtLeast(version){return version === '6.1';}",
                        ),
                    ),
                )
                legacy_page = await legacy.new_page()
                legacy_page.on("pageerror", lambda error: browser_errors.append(str(error)))
                await legacy_page.goto(f"http://127.0.0.1:{port}/")
                await legacy_page.get_by_role("heading", name="Your events").wait_for()
                assert await legacy_page.evaluate("window.testHeaderColor") == "secondary_bg_color"
                assert (
                    await legacy_page.evaluate("window.testBackgroundColor") == "secondary_bg_color"
                )
                assert await legacy_page.evaluate("window.testBottomBarColor === undefined")
                await browser.close()
            assert not browser_errors, browser_errors
            print(
                "Browser QA passed: QR export, MCQ forms, 10-row pagination, Android/iOS layouts, light/dark themes, safe areas, unsaved changes, native geometry and controls at 320/390/900px."
            )
            print("Synthetic screenshots:", OUT)
        finally:
            await runner.cleanup()
            await db.close()


asyncio.run(main())
