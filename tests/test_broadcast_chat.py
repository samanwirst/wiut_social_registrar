from datetime import datetime, timezone
from uuid import uuid4

import pytest
from aiogram.methods import CopyMessage, SendMessage
from aiogram.types import Chat, Message, MessageId, User

from tests import test_bot
from tests.test_bot import callback, methods, register, send

bot_app = test_bot.app


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["new_form", "new_event"])
async def test_creation_commands_share_the_same_form_workflow(bot_app, command):
    app = bot_app
    await register(app)
    replies = await send(app, f"/{command} SU Advisors")
    forms = await app.event_repository.owned_events(100)
    assert forms.events[0].title == "SU Advisors"
    assert "Form created" in replies[-1].text
    assert "Choose Event" not in replies[-1].text
    await send(app, f"/{command}")
    assert (await app.event_repository.owned_events(100)).events[0].title == "New Form"


@pytest.mark.asyncio
@pytest.mark.parametrize("rich", [False, True])
async def test_native_composition_requires_owner_preview_and_confirmation_and_preserves_message(
    rich, bot_app
):
    app = bot_app
    await register(app)
    form = await app.event_repository.create(100, "SU Advisors")
    await app.event_repository.visit(100, form.id)
    draft = await app.broadcast_repository.create(100, form.id, [100], str(uuid4()))
    ids = iter(range(500, 600))

    async def transport(bot, method, **kwargs):
        if isinstance(method, CopyMessage):
            return MessageId(message_id=next(ids))
        if isinstance(method, SendMessage):
            return Message(
                message_id=next(ids),
                date=datetime.now(timezone.utc),
                chat=Chat(id=100, type="private"),
                from_user=User(id=123456789, is_bot=True, first_name="Bot"),
                text=method.text,
            )
        return True

    app.bot.session.side_effect = transport
    replies = await send(app, "/start compose_" + draft["id"])
    assert replies[-1].reply_markup.force_reply
    async with app.database.transaction() as session:
        from app.models import Broadcast

        prompt_id = (await session.get(Broadcast, draft["id"])).prompt_message_id
    prompt = Message(
        message_id=prompt_id,
        date=datetime.now(timezone.utc),
        chat=Chat(id=100, type="private"),
        from_user=User(id=123456789, is_bot=True, first_name="Bot"),
        text="Write your message",
    )
    fields = (
        {
            "rich_message": {
                "blocks": [
                    {
                        "type": "paragraph",
                        "text": {"type": "bold", "text": "Hello"},
                    }
                ]
            }
        }
        if rich
        else {"entities": [{"type": "bold", "offset": 0, "length": 5}]}
    )
    # Use a real incoming Telegram update; no parse-mode conversion or content storage.
    replies = await send(app, None if rich else "Hello students", reply_to_message=prompt, **fields)
    assert replies[-1].reply_markup.inline_keyboard[0][0].text == "Send to 1 recipient"
    ready = await app.broadcast_repository.get(100, draft["id"])
    assert ready["status"] == "preview" and ready["content_kind"] == (
        "rich_message" if rich else "text"
    )
    assert await app.broadcast_repository.claim() is None
    copies = methods(app, CopyMessage)
    assert len(copies) == 1 and copies[0].message_id == 1
    await callback(app, f"bc:send:{draft['id']}:{ready['revision']}", user_id=200)
    assert (await app.broadcast_repository.get(100, draft["id"]))["status"] == "preview"
    await callback(app, f"bc:send:{draft['id']}:{ready['revision']}")
    claim = await app.broadcast_repository.claim()
    assert claim["source_message_id"] == ready["source_message_id"] and claim["telegram_id"] == 100
    from app.services.broadcast_worker import BroadcastWorker

    await BroadcastWorker(app.broadcast_repository, app.bot).deliver(claim)
    assert len(methods(app, CopyMessage)) == 2
    assert methods(app, CopyMessage)[-1].message_id == ready["source_message_id"]
    assert methods(app, CopyMessage)[-1].caption is None
    assert (await app.broadcast_repository.get(100, draft["id"]))["counts"] == {"sent": 1}
    assert ready["original_message_id"] == 1
    await send(app, "/start message_" + draft["id"], user_id=200)
    assert len(methods(app, CopyMessage)) == 2
    await send(app, "/start message_" + draft["id"])
    opened = methods(app, CopyMessage)[-1]
    assert len(methods(app, CopyMessage)) == 3
    assert opened.chat_id == opened.from_chat_id == 100
    assert opened.message_id == ready["source_message_id"]
    assert opened.reply_parameters.message_id == ready["original_message_id"]
    assert opened.reply_parameters.allow_sending_without_reply
    assert await app.broadcast_repository.claim() is None
