from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from aiogram.types import MessageId, User
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.broadcasts import BroadcastRepository
from app.dialogs.broadcasts import confirmation
from app.event_errors import EventError
from app.models import Broadcast, BroadcastRecipient
from app.services.broadcast_worker import BroadcastWorker
from tests import test_bot
from tests.test_bot import callback, register, send
from tests.test_event_forms import configured, registered

bot_app = test_bot.app


@pytest.mark.asyncio
async def test_announcement_freezes_all_users_and_requires_explicit_admin_confirmation(repository):
    await registered(repository, 100)
    repo = BroadcastRepository(repository.db, clock=repository.clock, admin_ids=(100,))
    request = str(uuid4())
    draft = await repo.prepare_announcement(100, request, 777, "rich_message")
    assert draft["event_id"] is None and draft["total"] == 2 and draft["status"] == "preview"
    assert await repo.claim() is None
    assert await repo.prepare_announcement(100, request, 777, "rich_message") == draft
    with pytest.raises(EventError):
        await repo.prepare_announcement(100, request, 778, "rich_message")
    with pytest.raises(EventError):
        await repo.prepare_announcement(200, str(uuid4()), 777, "rich_message")
    with pytest.raises(EventError):
        await BroadcastRepository(repository.db).get(100, draft["id"])
    with pytest.raises(EventError):
        await repo.queue(100, draft["id"], draft["revision"] + 1)
    await repository.touch_user(User(id=300, first_name="Later user", is_bot=False))
    await repo.queue(100, draft["id"], draft["revision"])
    await repo.queue(100, draft["id"], draft["revision"])
    bot = SimpleNamespace(copy_message=AsyncMock(return_value=MessageId(message_id=888)))
    worker = BroadcastWorker(repo, bot)
    recipients = []
    while claim := await repo.claim():
        recipients.append(claim["telegram_id"])
        await worker.deliver(claim)
    assert recipients == [100, 200]
    assert (await repo.get(100, draft["id"]))["counts"] == {"sent": 2}
    for call in bot.copy_message.await_args_list:
        assert call.kwargs["message_id"] == 777
        assert call.kwargs["from_chat_id"] == 100
        assert "caption" not in call.kwargs and "parse_mode" not in call.kwargs
        assert call.kwargs["allow_paid_broadcast"] is False
    assert confirmation(draft).inline_keyboard[0][0].text == "Send to everyone"
    assert len(confirmation(draft).inline_keyboard) == 1
    assert confirmation(draft, can_send=False) is None


@pytest.mark.asyncio
async def test_announcement_callback_cannot_be_used_by_another_user_or_removed_admin(bot_app):
    app = bot_app
    await register(app)
    await send(app, "/start", user_id=200)
    app.broadcast_repository.admin_ids = frozenset({100})
    draft = await app.broadcast_repository.prepare_announcement(
        100, str(uuid4()), 777, "rich_message"
    )
    await callback(app, f"bc:send:{draft['id']}:{draft['revision']}", user_id=200)
    assert await app.broadcast_repository.claim() is None
    app.broadcast_repository.admin_ids = frozenset()
    await callback(app, f"bc:send:{draft['id']}:{draft['revision']}")
    assert await app.broadcast_repository.claim() is None
    app.broadcast_repository.admin_ids = frozenset({100})
    await callback(app, f"bc:send:{draft['id']}:{draft['revision']}")
    assert (await app.broadcast_repository.get(100, draft["id"]))["status"] == "queued"


@pytest.mark.asyncio
async def test_announcement_cancel_invalidates_confirmation_and_preserves_submitted_data(
    repository,
):
    await registered(repository, 100)
    repo = BroadcastRepository(repository.db, clock=repository.clock, admin_ids=(100,))
    draft = await repo.prepare_announcement(100, str(uuid4()), 777, "text")
    await repository.cancel_current(100)
    with pytest.raises(EventError):
        await repo.queue(100, draft["id"], draft["revision"])
    assert await repository.verified(100)
    assert await repo.claim() is None


@pytest.mark.asyncio
async def test_announcement_migration_preserves_existing_broadcast_audiences_and_foreign_keys(
    repository,
):
    events, event = await configured(repository)
    await events.submit_form(
        100, event.id, {event.questions[0]["id"]: "Answer"}, event.form_revision
    )
    repo = BroadcastRepository(repository.db, clock=repository.clock, admin_ids=(100,))
    original = await repo.create(100, event.id, [100], str(uuid4()))

    def downgrade(connection):
        config = Config("alembic.ini")
        config.attributes["connection"] = connection
        command.downgrade(config, "0009_anonymous_forms")

    async with repository.db.engine.begin() as connection:
        await connection.run_sync(downgrade)
    await repository.db.migrate()
    assert await repo.get(100, original["id"]) == original
    async with repository.db.transaction() as session:
        assert await session.scalar(select(func.count()).select_from(BroadcastRecipient)) == 1
    with pytest.raises(IntegrityError):
        async with repository.db.transaction(write=True) as session:
            session.add(
                BroadcastRecipient(
                    broadcast_id=str(uuid4()),
                    telegram_user_id=100,
                    status="pending",
                    attempts=0,
                    next_attempt_at=repository.clock(),
                    updated_at=repository.clock(),
                )
            )
    await repo.prepare_announcement(100, str(uuid4()), 777, "rich_message")
    with pytest.raises(RuntimeError, match="announcements"):
        async with repository.db.engine.begin() as connection:
            await connection.run_sync(downgrade)
    async with repository.db.transaction() as session:
        assert await session.scalar(select(func.count()).select_from(Broadcast)) == 2
