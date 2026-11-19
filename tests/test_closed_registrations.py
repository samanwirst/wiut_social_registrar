import pytest

from tests import test_bot
from tests.test_bot import callback, methods, reach_education_step, send
from tests.test_event_forms import configuration, registered

bot_app = test_bot.app


@pytest.mark.asyncio
async def test_closed_form_is_reported_to_new_visitors_and_does_not_start_verification(bot_app):
    app = bot_app
    await test_bot.register(app)
    event = await app.event_repository.create(100, "Closed form")
    await app.event_repository.configure(
        100, event.id, configuration(event, registration_open=False)
    )
    before = app.registrar_service.send_verification_code.await_count
    replies = await send(app, f"/start event_{event.id}", user_id=200)
    assert "Registration closed" in replies[-1].text and event.title in replies[-1].text
    assert await app.registration_repository.pending(200) is None
    assert await app.event_repository.pending_titles(200) == []
    assert app.registrar_service.send_verification_code.await_count == before


@pytest.mark.asyncio
async def test_closing_during_student_registration_never_claims_the_form_was_completed(bot_app):
    app = bot_app
    await send(app, "/start", user_id=200)
    await registered(app.registration_repository, 200)
    event = await app.event_repository.create(200, "Closing while registering")
    await send(app, f"/start event_{event.id}")
    await reach_education_step(app)
    await app.event_repository.configure(
        200, event.id, configuration(event, registration_open=False)
    )
    await callback(app, "education:4")
    from aiogram.methods import SendMessage

    text = methods(app, SendMessage)[-1].text
    assert "Registration closed" in text and event.title in text
    assert "saved forms are complete" not in text
    assert await app.registration_repository.verified(100)
    assert (await app.event_repository.members(200, event.id)).total == 0
