"""Synthetic browser coverage for full answers, editing, and return navigation."""

import asyncio
import json


async def answer_geometry(page):
    await page.wait_for_function("""() => {
        const panel = document.querySelector('.answer-panel');
        const action = panel?.querySelector('.answer-actions button');
        if (!panel || !action) return false;
        const frame = panel.getBoundingClientRect(), button = action.getBoundingClientRect();
        return frame.top >= -1 && button.bottom <= innerHeight + 1;
    }""")
    bounds = await page.get_by_role("dialog").bounding_box()
    action = (
        await page.get_by_role("dialog")
        .get_by_role("button", name="Edit", exact=True)
        .bounding_box()
    )
    viewport = page.viewport_size
    assert bounds and action and viewport
    assert bounds["x"] >= -1 and bounds["y"] >= -1
    assert bounds["x"] + bounds["width"] <= viewport["width"] + 1
    assert action["y"] + action["height"] <= viewport["height"] + 1
    assert (
        bounds["width"] <= 561
        if viewport["width"] > 760
        else bounds["width"] >= viewport["width"] - 1
    )


async def check_long_answers(page, events, form_id, question, original, screenshots):
    initial_revision = (await events.answer_page(100, form_id, 1)).members[0]["row_revision"]
    await page.set_viewport_size({"width": 390, "height": 844})
    read = page.get_by_role("button", name=f"Read {question['label']} for Student 1010", exact=True)
    await read.wait_for()
    assert await read.get_by_text("Read more", exact=True).is_visible()
    preview = read.locator(".cell-preview")
    assert await preview.text_content() == original
    assert await preview.evaluate("node => node.clientHeight < node.scrollHeight")
    await read.scroll_into_view_if_needed()
    before = await page.evaluate("""() => ({x: scrollX, y: scrollY,
        left: document.querySelector('.scroll-table').scrollLeft,
        top: document.querySelector('.scroll-table').scrollTop})""")
    await read.click()
    dialog = page.get_by_role("dialog", name=question["label"], exact=True)
    try:
        await dialog.wait_for(timeout=5000)
    except Exception:
        await page.screenshot(path=str(screenshots / "answer-open-failure.png"))
        print("Answer screenshot:", screenshots / "answer-open-failure.png")
        raise
    assert await dialog.locator(".answer-text").text_content() == original
    assert await dialog.get_by_role("textbox").count() == 0
    assert await dialog.locator("b").count() == 0
    assert await page.evaluate("!['INPUT','TEXTAREA'].includes(document.activeElement.tagName)")
    await answer_geometry(page)
    await page.screenshot(path=str(screenshots / "mobile-full-answer.png"))
    await page.evaluate("window.testBack()")
    await dialog.wait_for(state="detached")
    await page.get_by_text("Page 2 of 2", exact=True).wait_for()
    assert await page.get_by_text("2 selected across pages", exact=True).is_visible()
    after = await page.evaluate("""() => ({x: scrollX, y: scrollY,
        left: document.querySelector('.scroll-table').scrollLeft,
        top: document.querySelector('.scroll-table').scrollTop})""")
    assert all(abs(before[key] - after[key]) <= 2 for key in before), (before, after)
    assert await read.evaluate("node => document.activeElement === node")
    assert await page.get_by_label("Select Student 1010", exact=True).is_checked()

    await read.click()
    await dialog.get_by_role("button", name="Edit", exact=True).click()
    field = dialog.get_by_role("textbox", name=question["label"], exact=True)
    assert await field.is_enabled()
    assert await field.input_value() == original
    assert await field.get_attribute("maxlength") == "2000"
    assert (await events.answer_page(100, form_id, 1)).members[0][
        "row_revision"
    ] == initial_revision
    updated = original + "\n\nReady to help with the next event"
    await field.fill(updated)
    await page.wait_for_function("() => window.testClosingConfirmation === true")
    await page.set_viewport_size({"width": 390, "height": 500})
    save = dialog.get_by_role("button", name="Save", exact=True)
    await page.wait_for_function(
        "() => document.querySelector('.answer-panel').getBoundingClientRect().height <= innerHeight + 1"
    )
    action = await save.bounding_box()
    assert action and action["y"] + action["height"] <= 501
    await page.screenshot(path=str(screenshots / "mobile-answer-editor-keyboard.png"))
    page.once("dialog", lambda prompt: prompt.dismiss())
    await page.evaluate("window.testBack()")
    assert await field.input_value() == updated

    path = f"**/api/forms/{form_id}/members/1010"

    async def reject(route):
        await route.fulfill(
            status=409,
            content_type="application/json",
            body=json.dumps({"error": "This row changed in another window. Refresh the table"}),
        )

    await page.route(path, reject)
    await save.click()
    await dialog.get_by_role("alert").get_by_text("This row changed", exact=False).wait_for()
    assert await field.input_value() == updated
    assert await page.evaluate("window.testClosingConfirmation")
    await page.unroute(path, reject)

    started, release = asyncio.Event(), asyncio.Event()
    submissions = []

    async def delay(route):
        submissions.append(route.request.method)
        started.set()
        await release.wait()
        await route.continue_()

    await page.route(path, delay)
    await save.click()
    await asyncio.wait_for(started.wait(), timeout=5)
    assert await save.is_disabled()
    await page.evaluate("window.testBack()")
    assert await dialog.is_visible()
    await dialog.get_by_role("form").evaluate("form => form.requestSubmit()")
    release.set()
    await dialog.get_by_role("button", name="Edit", exact=True).wait_for()
    await page.unroute(path, delay)
    assert submissions == ["PATCH"]
    assert await dialog.locator(".answer-text").text_content() == updated
    await page.wait_for_function("() => window.testClosingConfirmation === false")
    saved = await events.answer_page(100, form_id, 1)
    assert saved.members[0]["answers"][question["id"]] == updated
    await page.set_viewport_size({"width": 1280, "height": 1000})
    await answer_geometry(page)
    await page.screenshot(path=str(screenshots / "desktop-full-answer.png"))
    await dialog.get_by_role("button", name="Close answer", exact=True).click()
    await dialog.wait_for(state="detached")

    # An initially short/empty text cell can expand without losing typed changes.
    await page.get_by_role("button", name="Add column", exact=True).click()
    await page.get_by_label("Column name", exact=True).fill("Notes")
    await page.get_by_role("button", name="Save column", exact=True).click()
    await page.get_by_role("button", name="Edit Notes for Student 1010", exact=True).click()
    inline = page.get_by_role("form", name="Edit Notes for Student 1010", exact=True)
    await inline.get_by_role("textbox").fill(original)
    await inline.get_by_role("button", name="Expand editor", exact=True).click()
    notes = page.get_by_role("dialog", name="Notes", exact=True)
    assert await notes.get_by_role("textbox", name="Notes", exact=True).input_value() == original
    await notes.get_by_role("button", name="Save", exact=True).click()
    await notes.get_by_role("button", name="Edit", exact=True).wait_for()
    assert await notes.locator(".answer-text").text_content() == original
    await page.evaluate("window.testBack()")
    await notes.wait_for(state="detached")
    assert await page.get_by_text("2 selected across pages", exact=True).is_visible()
    saved = await events.answer_page(100, form_id, 1)
    assert original in saved.members[0]["organizer_values"].values()

    # Closing a clean answer must preserve the form's separate unsaved-change guard.
    await page.get_by_role("tab", name="Overview", exact=True).click()
    await page.get_by_label("Description", exact=True).fill(
        "A revised description for this synthetic form"
    )
    await page.wait_for_function("() => window.testClosingConfirmation === true")
    await page.get_by_role("tab", name="People", exact=True).click()
    await page.get_by_role(
        "button", name=f"Read {question['label']} for Student 1001", exact=True
    ).click()
    await page.get_by_role("dialog").wait_for()
    await page.evaluate("window.testBack()")
    await page.get_by_role("dialog").wait_for(state="detached")
    assert await page.evaluate("window.testClosingConfirmation")
    await page.get_by_role("tab", name="Overview", exact=True).click()
    await page.get_by_role("button", name="Save changes", exact=True).click()
    await page.get_by_text("All changes saved", exact=True).wait_for()
    await page.wait_for_function("() => window.testClosingConfirmation === false")
    await page.get_by_role("tab", name="People", exact=True).click()
    await page.get_by_role("button", name="Next", exact=True).click()
    await page.get_by_text("Page 2 of 2", exact=True).wait_for()
