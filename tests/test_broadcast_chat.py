from datetime import datetime, timezone
from uuid import uuid4

import pytest
from aiogram.methods import CopyMessage, SendMessage, SendRichMessage
from aiogram.types import Chat, Message, MessageId, User

from app.dialogs.broadcast_content import send_preview
from app.event_errors import EventError
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
@pytest.mark.parametrize("kind", ["text", "rich_message", "photo", "document"])
async def test_native_composition_requires_owner_preview_and_confirmation_and_preserves_message(
    kind, bot_app
):
    app = bot_app
    await register(app)
    form = await app.event_repository.create(100, "SU <Advisors> & 🎓 _team_")
    await app.event_repository.visit(100, form.id)
    draft = await app.broadcast_repository.create(100, form.id, [100], str(uuid4()))
    ids = iter(range(500, 600))

    async def transport(bot, method, **kwargs):
        if isinstance(method, CopyMessage):
            return MessageId(message_id=next(ids))
        if isinstance(method, (SendMessage, SendRichMessage)):
            return Message(
                message_id=next(ids),
                date=datetime.now(timezone.utc),
                chat=Chat(id=100, type="private"),
                from_user=User(id=123456789, is_bot=True, first_name="Bot"),
                text=getattr(method, "text", None),
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
    fields = {
        "rich_message": {
            "rich_message": {
                "blocks": [
                    {
                        "type": "paragraph",
                        "text": {"type": "bold", "text": "Hello"},
                    }
                ]
            }
        },
        "text": {
            "entities": [{"type": "bold", "offset": 0, "length": 5}],
            "link_preview_options": {"is_disabled": True},
        },
        "photo": {
            "photo": [{"file_id": "photo", "file_unique_id": "unique", "width": 40, "height": 40}],
            "caption": "Hello 🎉 students",
            "caption_entities": [{"type": "bold", "offset": 0, "length": 5}],
            "show_caption_above_media": True,
        },
        "document": {
            "document": {"file_id": "document", "file_unique_id": "unique"},
        },
    }[kind]
    # Use a real incoming Telegram update; no parse-mode conversion or content storage.
    replies = await send(
        app, "Hello 🎉 students" if kind == "text" else None, reply_to_message=prompt, **fields
    )
    assert replies[-1].reply_markup.inline_keyboard[0][0].text == "Send to 1 recipient"
    ready = await app.broadcast_repository.get(100, draft["id"])
    assert ready["status"] == "preview" and ready["content_kind"] == kind
    assert await app.broadcast_repository.claim() is None
    copies = methods(app, CopyMessage)
    initial_copies = int(kind in {"photo", "document"})
    assert len(copies) == initial_copies
    footer = "By " + form.title
    if kind == "rich_message":
        rich = methods(app, SendRichMessage)[-1].rich_message
        assert rich.blocks[0].text.type == "bold" and rich.blocks[0].text.text == "Hello"
        assert rich.blocks[-1].text.type == "italic" and rich.blocks[-1].text.text == footer
    else:
        preview = copies[0] if initial_copies else replies[-2]
        text = preview.caption if initial_copies else preview.text
        entities = preview.caption_entities if initial_copies else preview.entities
        original = "" if kind == "document" else "Hello 🎉 students\n\n"
        assert text == original + footer
        assert preview.parse_mode is None
        assert entities[-1].type == "italic"
        assert entities[-1].offset == len(original.encode("utf-16-le")) // 2
        assert entities[-1].length == len(footer.encode("utf-16-le")) // 2
        if kind != "document":
            assert entities[0].type == "bold" and entities[0].length == 5
        if kind == "photo":
            assert preview.show_caption_above_media
        if kind == "text":
            assert preview.link_preview_options.is_disabled
        if initial_copies:
            assert preview.message_id == 1
    await app.event_repository.configure(
        100,
        form.id,
        {
            "title": "Renamed form",
            "description": form.description,
            "registration_open": form.registration_open,
            "response_retention_days": form.response_retention_days,
            "questions": form.questions,
            "revision": form.revision,
        },
    )
    await callback(app, f"bc:send:{draft['id']}:{ready['revision']}", user_id=200)
    assert (await app.broadcast_repository.get(100, draft["id"]))["status"] == "preview"
    await callback(app, f"bc:send:{draft['id']}:{ready['revision']}")
    claim = await app.broadcast_repository.claim()
    assert claim["source_message_id"] == ready["source_message_id"] and claim["telegram_id"] == 100
    from app.services.broadcast_worker import BroadcastWorker

    await BroadcastWorker(app.broadcast_repository, app.bot).deliver(claim)
    assert len(methods(app, CopyMessage)) == initial_copies + 1
    assert methods(app, CopyMessage)[-1].message_id == ready["source_message_id"]
    assert methods(app, CopyMessage)[-1].caption is None
    assert (await app.broadcast_repository.get(100, draft["id"]))["counts"] == {"sent": 1}
    assert ready["original_message_id"] == 1
    await send(app, "/start message_" + draft["id"], user_id=200)
    assert len(methods(app, CopyMessage)) == initial_copies + 1
    await send(app, "/start message_" + draft["id"])
    opened = methods(app, CopyMessage)[-1]
    assert len(methods(app, CopyMessage)) == initial_copies + 2
    assert opened.chat_id == opened.from_chat_id == 100
    assert opened.message_id == ready["source_message_id"]
    assert opened.reply_parameters.message_id == ready["original_message_id"]
    assert opened.reply_parameters.allow_sending_without_reply
    assert await app.broadcast_repository.claim() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,limit", [("text", 4096), ("photo", 1024)])
@pytest.mark.parametrize("too_long", [False, True])
async def test_attribution_reserves_telegram_space_without_truncating_content(
    bot_app, kind, limit, too_long
):
    title = "🎓 <Form> & _team_"
    suffix = "\n\nBy " + title
    body = "x" * (limit - len(suffix.encode("utf-16-le")) // 2 + int(too_long))
    fields = (
        {"text": body}
        if kind == "text"
        else {
            "photo": [{"file_id": "photo", "file_unique_id": "unique", "width": 40, "height": 40}],
            "caption": body,
        }
    )
    message = Message(
        message_id=1,
        date=datetime.now(timezone.utc),
        chat=Chat(id=100, type="private"),
        from_user=User(id=100, is_bot=False, first_name="Organizer"),
        **fields,
    ).as_(bot_app.bot)
    if too_long:
        with pytest.raises(EventError, match="Shorten your message"):
            await send_preview(message, title, kind)
        bot_app.bot.session.assert_not_awaited()
    else:
        await send_preview(message, title, kind)
        prepared = bot_app.bot.session.await_args.args[1]
        assert (prepared.text if kind == "text" else prepared.caption) == body + suffix
        assert prepared.allow_paid_broadcast is False


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["photo", "video", "animation", "audio", "document", "voice_note"])
async def test_rich_attribution_preserves_nested_media_captions_and_formatting(bot_app, kind):
    media = {"file_id": "file", "file_unique_id": "unique"}
    if kind in {"photo", "video", "animation"}:
        media.update(width=100, height=100)
    if kind in {"video", "animation", "audio", "voice_note"}:
        media["duration"] = 1
    block = {
        "type": kind,
        kind: [{**media, "file_id": "small", "width": 10, "height": 10}, media]
        if kind == "photo"
        else media,
        "caption": {"text": {"type": "bold", "text": "Keep this caption"}},
    }
    if kind in {"photo", "video", "animation"}:
        block["has_spoiler"] = True
    message = Message(
        message_id=1,
        date=datetime.now(timezone.utc),
        chat=Chat(id=100, type="private"),
        from_user=User(id=100, is_bot=False, first_name="Organizer"),
        rich_message={
            "is_rtl": True,
            "blocks": [{"type": "details", "summary": "More", "is_open": True, "blocks": [block]}],
        },
    ).as_(bot_app.bot)
    original = message.rich_message.model_dump()
    await send_preview(message, "<Team> 🎓", "rich_message")
    prepared = methods(bot_app, SendRichMessage)[-1].rich_message
    assert prepared.is_rtl and prepared.skip_entity_detection
    assert prepared.blocks[0].summary == "More" and prepared.blocks[0].is_open
    nested = prepared.blocks[0].blocks[0]
    assert nested.caption.text.type == "bold"
    assert nested.caption.text.text == "Keep this caption"
    assert getattr(nested, kind).media == "file"
    if kind in {"photo", "video", "animation"}:
        assert getattr(nested, kind).has_spoiler
    assert prepared.blocks[-1].text.type == "italic"
    assert prepared.blocks[-1].text.text == "By <Team> 🎓"
    assert message.rich_message.model_dump() == original
