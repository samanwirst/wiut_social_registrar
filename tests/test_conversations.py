from uuid import uuid4

import pytest

from app.broadcasts import BroadcastRepository
from app.event_repository import EventError
from tests.test_event_forms import configured, question


@pytest.mark.asyncio
@pytest.mark.parametrize("queued", [False, True])
async def test_cancel_discards_composer_without_touching_confirmed_deliveries_or_registration(
    repository, queued
):
    events, event = await configured(repository, [question()])
    await events.submit_form(100, event.id, {event.questions[0]["id"]: "Done"}, event.form_revision)
    broadcasts = BroadcastRepository(repository.db, clock=repository.clock)
    draft = await broadcasts.create(100, event.id, [100], str(uuid4()))
    await broadcasts.compose(100, draft["id"], 7)
    preview = await broadcasts.preview(100, draft["id"], 7, 8, "text")
    if queued:
        await broadcasts.queue(100, draft["id"], preview["revision"])
    before = await repository.verified(100)
    await repository.cancel_current(100)
    assert await repository.verified(100) == before
    assert (await events.members(100, event.id)).total == 1
    after = await broadcasts.get(100, draft["id"])
    assert after["status"] == ("queued" if queued else "cancelled")
    assert await broadcasts.reply_draft(100, 7) is None
    if not queued:
        with pytest.raises(EventError):
            await broadcasts.queue(100, draft["id"], preview["revision"])
