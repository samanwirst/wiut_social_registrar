import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from aiogram.methods import (
    AnswerCallbackQuery,
    EditMessageReplyMarkup,
    EditMessageText,
    SendMessage,
    SendPhoto,
    SendRichMessage,
    SetMyCommands,
)
from aiogram.types import Chat, Contact, Message, ReplyKeyboardRemove, Update, User
from sqlalchemy import select

from app.bot import BotApp
from app.models import Event, EventRegistration, PendingEventRegistration
from app.models import TelegramUser as StoredTelegramUser
from config import BotSettings
from registrar.config import Settings
from registrar.errors import GraphError, SendStatusUnknown
from registrar.models import Student

TEST_TOKEN = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789"
PERSON = Student(
    "00000001",
    "Student <Name>",
    "student@example.test",
    account="00000001@example.test",
    graph_id="00000000-0000-0000-0000-000000000001",
    given_name="Student",
    surname="Name",
)


@pytest_asyncio.fixture
async def app(monkeypatch, tmp_path):
    service = AsyncMock()
    service.find_student.return_value = PERSON
    monkeypatch.setattr("app.bot.RegistrarService", lambda _: service)
    instance = BotApp(
        BotSettings(TEST_TOKEN, Settings(tmp_path / ".env"), verification_secret="ab" * 32)
    )
    await instance.database.migrate()
    await instance.bot.session.close()
    instance.bot.session = AsyncMock()
    instance.bot._me = User(
        id=123456789, is_bot=True, first_name="Registrar", username="test_registrar_bot"
    )
    try:
        yield instance
    finally:
        await instance.shutdown()


async def send(app, text=None, *, user_id=100, chat_type="private", contact=None, **message_fields):
    update = Update(
        update_id=1,
        message=Message(
            message_id=1,
            date=datetime.now(timezone.utc),
            chat=Chat(id=user_id, type=chat_type),
            from_user=User(
                id=user_id,
                is_bot=False,
                first_name="User",
                username="test_user",
                language_code="en",
            ),
            text=text,
            contact=contact,
            **message_fields,
        ),
    )
    before = len(app.bot.session.call_args_list)
    await app.dp.feed_update(app.bot, update)
    return [
        call.args[1]
        for call in app.bot.session.call_args_list[before:]
        if isinstance(call.args[1], SendMessage)
    ]


async def register(app, user_id=100, *, level="cifs"):
    await send(app, "00000001", user_id=user_id)
    code = app.registrar_service.send_verification_code.await_args.args[1]
    await send(app, code, user_id=user_id)
    await send(
        app,
        user_id=user_id,
        contact=Contact(phone_number="+998901234567", first_name="User", user_id=user_id),
    )
    return await choose_level(app, user_id=user_id, level=level)


async def choose_level(app, user_id=100, level="cifs"):
    before = len(app.bot.session.call_args_list)
    await callback(app, "education:" + level, user_id=user_id)
    return [
        call.args[1]
        for call in app.bot.session.call_args_list[before:]
        if isinstance(call.args[1], SendMessage)
    ]


@pytest.mark.asyncio
async def test_registration_hides_profile_until_email_phone_and_education_are_confirmed(app):
    replies = await send(app, "/start")
    assert "own student ID" in replies[-1].text
    app.registrar_service.assert_not_called()
    replies = await send(app, "00000001")
    assert "6-digit code" in replies[-1].text
    assert "student@example.test" not in replies[-1].text
    assert "Student <Name>" not in replies[-1].text
    app.registrar_service.find_student.assert_awaited_once_with("00000001", refresh=True)
    code = app.registrar_service.send_verification_code.await_args.args[1]
    assert len(code) == 6 and code.isascii() and code.isdigit()
    wrong = "111111" if code != "111111" else "222222"
    replies = await send(app, wrong)
    assert "Incorrect code" in replies[-1].text
    assert await app.registration_repository.verified(100) is None
    replies = await send(app, code)
    assert "Your email is verified" in replies[-1].text
    assert "Student <Name>" not in replies[-1].text
    button = replies[-1].reply_markup.keyboard[0][0]
    assert button.request_contact and button.text == "Share phone number"
    assert await app.registration_repository.verified(100) is None
    replies = await send(
        app, contact=Contact(phone_number="+998901234567", first_name="User", user_id=100)
    )
    assert "education level" in replies[-1].text
    assert await app.registration_repository.verified(100) is None
    assert await app.registration_repository.awaiting_education(100)
    assert [button.text for row in replies[-1].reply_markup.inline_keyboard for button in row] == [
        "CIFS",
        "Level 4",
        "Level 5",
        "Level 6",
    ]
    replies = await choose_level(app)
    assert "Registration complete" in replies[-1].text
    assert "Name: Student <Name>" in replies[-1].text
    assert replies[-1].parse_mode is None
    assert replies[-1].reply_markup is None
    assert (await app.registration_repository.verified(100)).student_id == "00000001"
    replies = await send(app, "/start")
    assert len(replies) == 1
    assert "You're all set!" in replies[0].text
    assert PERSON.student_id not in replies[0].text and PERSON.email not in replies[0].text
    assert isinstance(replies[0].reply_markup, ReplyKeyboardRemove)
    assert app.registrar_service.send_verification_code.await_count == 1


@pytest.mark.asyncio
async def test_me_shows_only_the_profile_linked_to_the_current_telegram_user(app):
    await register(app)
    other = Student(
        "00000002", "Other Student", "other@example.test", account="00000002@example.test"
    )
    app.registrar_service.find_student.return_value = other
    await register(app, user_id=200, level="6")
    app.registrar_service.reset_mock()

    for user_id, own, foreign, level in (
        (100, PERSON, other, "CIFS"),
        (200, other, PERSON, "Level 6"),
    ):
        replies = await send(app, "/me", user_id=user_id)
        assert len(replies) == 1
        assert own.student_id in replies[0].text and own.email in replies[0].text
        assert own.name in replies[0].text
        assert f"Education level: {level}" in replies[0].text
        assert foreign.student_id not in replies[0].text and foreign.email not in replies[0].text
        assert replies[0].reply_markup is None
    app.registrar_service.find_student.assert_not_called()
    app.registrar_service.send_verification_code.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text", ["00000001", "00000002", "asd", "/me 00000002", "/me@test_registrar_bot 00000002"]
)
async def test_registered_user_cannot_search_for_profiles_or_select_a_me_target(app, text):
    await register(app)
    app.registrar_service.reset_mock()
    app.registrar_service.find_student.side_effect = AssertionError("Chat must not search profiles")
    replies = await send(app, text)
    assert "/me" in replies[-1].text
    assert PERSON.name not in replies[-1].text and PERSON.email not in replies[-1].text
    assert "00000002" not in replies[-1].text
    app.registrar_service.find_student.assert_not_called()
    app.registrar_service.send_verification_code.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["new", "code", "phone", "education"])
async def test_me_hides_profile_until_all_registration_steps_are_complete(app, stage):
    if stage != "new":
        await send(app, "00000001")
    if stage in {"phone", "education"}:
        await send(app, app.registrar_service.send_verification_code.await_args.args[1])
    if stage == "education":
        await send(
            app, contact=Contact(phone_number="+998901234567", first_name="User", user_id=100)
        )
    app.registrar_service.reset_mock()
    replies = await send(app, "/me")
    assert len(replies) == 1
    for private_value in (PERSON.student_id, PERSON.name, PERSON.email, PERSON.account):
        assert private_value not in replies[0].text
    app.registrar_service.find_student.assert_not_called()
    app.registrar_service.send_verification_code.assert_not_called()


@pytest.mark.asyncio
async def test_me_never_shares_profile_in_a_group(app):
    await register(app)
    app.registrar_service.reset_mock()
    replies = await send(app, "/me", chat_type="group")
    assert "private chat" in replies[-1].text
    assert PERSON.name not in replies[-1].text and PERSON.email not in replies[-1].text
    app.registrar_service.find_student.assert_not_called()
    app.registrar_service.send_verification_code.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("registered", [False, True])
@pytest.mark.parametrize(
    "text",
    [
        "/find",
        "/find 00000001",
        "/send",
        "/mail 00000001",
        "/members",
        "/members invalid-id",
        "/cancel",
    ],
)
async def test_removed_commands_cannot_look_up_or_send(app, text, registered):
    if registered:
        await register(app)
        app.registrar_service.reset_mock()
    replies = await send(app, text)
    assert "command is not available" in replies[-1].text
    app.registrar_service.find_student.assert_not_called()
    app.registrar_service.send_verification_code.assert_not_called()


@pytest.mark.asyncio
async def test_nonexistent_student_gets_no_email(app):
    app.registrar_service.find_student.return_value = None
    replies = await send(app, "99999999")
    assert "No student found" in replies[-1].text
    app.registrar_service.send_verification_code.assert_not_called()


@pytest.mark.asyncio
async def test_invalid_id_is_rejected_before_graph(app):
    replies = await send(app, "bad-id")
    assert "1 to 32 digits" in replies[-1].text
    app.registrar_service.find_student.assert_not_called()


@pytest.mark.asyncio
async def test_graph_errors_do_not_expose_host_configuration(app):
    app.registrar_service.find_student.side_effect = GraphError("Run cli.py --login on the host.")
    replies = await send(app, "00000001")
    assert "temporarily unavailable" in replies[-1].text
    assert "cli.py" not in replies[-1].text


@pytest.mark.asyncio
async def test_unknown_submission_keeps_code_valid_and_does_not_retry(app):
    app.registrar_service.send_verification_code.side_effect = SendStatusUnknown("Check Sent Items")
    replies = await send(app, "00000001")
    assert "did not confirm" in replies[-1].text
    code = app.registrar_service.send_verification_code.await_args.args[1]
    replies = await send(app, code)
    assert "Your email is verified" in replies[-1].text
    assert await app.registration_repository.verified(100) is None
    replies = await send(
        app, contact=Contact(phone_number="+998901234567", first_name="User", user_id=100)
    )
    assert "education level" in replies[-1].text
    replies = await choose_level(app)
    assert "Registration complete" in replies[-1].text
    assert app.registrar_service.send_verification_code.await_count == 1


@pytest.mark.asyncio
async def test_definite_submission_failure_invalidates_code(app):
    app.registrar_service.send_verification_code.side_effect = GraphError("HTTP 403")
    replies = await send(app, "00000001")
    assert "temporarily unavailable" in replies[-1].text
    code = app.registrar_service.send_verification_code.await_args.args[1]
    replies = await send(app, code)
    assert "could not be submitted" in replies[-1].text
    assert await app.registration_repository.verified(100) is None


@pytest.mark.asyncio
async def test_repeated_and_concurrent_requests_send_one_email(app):
    await asyncio.gather(send(app, "00000001"), send(app, "00000001"))
    replies = await send(app, "/resend")
    assert "wait" in replies[-1].text
    assert app.registrar_service.send_verification_code.await_count == 1


@pytest.mark.asyncio
async def test_private_chat_required(app):
    replies = await send(app, "00000001", chat_type="group")
    assert "private chat" in replies[-1].text
    app.registrar_service.find_student.assert_not_called()


@pytest.mark.asyncio
async def test_removed_cancel_preserves_pending_code_and_cooldown(app):
    await send(app, "00000001")
    code = app.registrar_service.send_verification_code.await_args.args[1]
    replies = await send(app, "/cancel")
    assert "not available" in replies[-1].text
    assert await app.registration_repository.pending(100) is not None
    replies = await send(app, "/resend")
    assert "wait" in replies[-1].text
    replies = await send(app, code)
    assert replies[-1].reply_markup.keyboard[0][0].request_contact
    assert app.registrar_service.send_verification_code.await_count == 1
    assert await app.registration_repository.verified(100) is None


@pytest.mark.asyncio
async def test_unexpected_error_never_logs_private_exception_text(app, caplog):
    app.registrar_service.find_student.side_effect = RuntimeError("private-token-in-url")
    replies = await send(app, "00000001")
    assert "Something went wrong" in replies[-1].text
    assert "private-token-in-url" not in caplog.text


@pytest.mark.asyncio
async def test_old_email_callback_is_not_handled(app):
    update = Update(
        update_id=1,
        callback_query={
            "id": "old-button",
            "from": {"id": 100, "is_bot": False, "first_name": "User"},
            "chat_instance": "private",
            "data": "send:00000001",
        },
    )
    await app.dp.feed_update(app.bot, update)
    app.registrar_service.send_verification_code.assert_not_called()
    app.bot.session.assert_not_called()


@pytest.mark.asyncio
async def test_contact_before_code_verification_does_not_register(app):
    await send(app, "00000001")
    replies = await send(
        app, contact=Contact(phone_number="+998901234567", first_name="User", user_id=100)
    )
    assert "Verify your Outlook email first" in replies[-1].text
    assert await app.registration_repository.verified(100) is None
    assert await app.registration_repository.pending(100) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("contact_user_id", [None, 200])
async def test_foreign_or_unidentified_contact_is_rejected(app, contact_user_id):
    await send(app, "00000001")
    code = app.registrar_service.send_verification_code.await_args.args[1]
    await send(app, code)
    replies = await send(
        app,
        contact=Contact(phone_number="+998901234567", first_name="Other", user_id=contact_user_id),
    )
    assert "your own Telegram contact" in replies[-1].text
    assert replies[-1].reply_markup.keyboard[0][0].request_contact
    assert await app.registration_repository.verified(100) is None


@pytest.mark.asyncio
async def test_forwarded_contact_is_rejected(app):
    await send(app, "00000001")
    await send(app, app.registrar_service.send_verification_code.await_args.args[1])
    replies = await send(
        app,
        contact=Contact(phone_number="+998901234567", first_name="User", user_id=100),
        forward_origin={
            "type": "user",
            "date": datetime.now(timezone.utc),
            "sender_user": {"id": 100, "is_bot": False, "first_name": "User"},
        },
    )
    assert "forwarded contacts" in replies[-1].text
    assert await app.registration_repository.verified(100) is None


@pytest.mark.asyncio
async def test_phone_step_blocks_text_lookups_and_resends_and_resumes_on_start(app):
    await send(app, "00000001")
    await send(app, app.registrar_service.send_verification_code.await_args.args[1])
    for text in ("+998901234567", "00000002", "/start", "/resend", "/find 00000002"):
        replies = await send(app, text)
        assert replies[-1].reply_markup.keyboard[0][0].request_contact
        assert "Student <Name>" not in replies[-1].text
    assert app.registrar_service.find_student.await_count == 1
    assert app.registrar_service.send_verification_code.await_count == 1
    assert await app.registration_repository.verified(100) is None


@pytest.mark.asyncio
async def test_removed_cancel_keeps_phone_step_and_verified_email(app):
    await send(app, "00000001")
    await send(app, app.registrar_service.send_verification_code.await_args.args[1])
    replies = await send(app, "/cancel")
    assert replies[-1].reply_markup.keyboard[0][0].request_contact
    assert await app.registration_repository.awaiting_phone(100)
    replies = await send(
        app, contact=Contact(phone_number="+998901234567", first_name="User", user_id=100)
    )
    assert "education level" in replies[-1].text
    assert app.registrar_service.send_verification_code.await_count == 1
    assert await app.registration_repository.verified(100) is None


@pytest.mark.asyncio
async def test_repeated_contact_does_not_repeat_registration(app):
    await register(app)
    replies = await send(
        app, contact=Contact(phone_number="+998909999999", first_name="User", user_id=100)
    )
    assert "already registered" in replies[-1].text
    assert replies[-1].reply_markup is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "command,title", [("/new_event", "New Event"), ("/new_event Welcome Night", "Welcome Night")]
)
@pytest.mark.parametrize("mini_app_url", ["", "https://events.example.test"])
async def test_new_event_sends_confirmation_without_registration_media(
    app, command, title, mini_app_url
):
    app.dp["mini_app_url"] = mini_app_url
    await register(app)
    replies = await send(app, command)
    assert len(replies) == 1
    reply = replies[0]
    assert title in reply.text and "Event created" in reply.text
    assert "https://t.me/" not in reply.text
    assert methods(app, SendPhoto) == []
    async with app.database.transaction() as session:
        event = (await session.scalars(select(Event))).one()
        assert event.title == title and event.creator_telegram_user_id == 100
    if mini_app_url:
        buttons = [button for row in reply.reply_markup.inline_keyboard for button in row]
        assert len(buttons) == 1 and buttons[0].text == "Manage event"
        assert buttons[0].web_app.url == f"{mini_app_url}/?event={event.id}"
        assert buttons[0].url is None
    else:
        assert reply.reply_markup is None


@pytest.mark.asyncio
async def test_unregistered_user_cannot_create_event(app):
    replies = await send(app, "/new_event")
    assert "Complete registration first" in replies[-1].text
    async with app.database.transaction() as session:
        assert list(await session.scalars(select(Event))) == []
    app.registrar_service.find_student.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("registered", [False, True])
async def test_plain_new_event_text_cannot_create_event(app, registered):
    if registered:
        await register(app)
    app.registrar_service.reset_mock()
    replies = await send(app, "New Event")
    assert ("/me" if registered else "1 to 32 digits") in replies[-1].text
    app.registrar_service.find_student.assert_not_called()
    assert methods(app, SendPhoto) == []
    async with app.database.transaction() as session:
        assert list(await session.scalars(select(Event))) == []


@pytest.mark.asyncio
async def test_event_link_enrolls_verified_student_once_without_graph_calls(app):
    await register(app)
    event = await app.event_repository.create(100, "Student Meetup")
    app.registrar_service.reset_mock()
    replies = await send(app, f"/start event_{event.id}")
    assert "You are registered for: Student Meetup" in replies[-1].text
    replies = await send(app, f"/start event_{event.id}")
    assert "already registered" in replies[-1].text
    async with app.database.transaction() as session:
        assert len(list(await session.scalars(select(EventRegistration)))) == 1
    app.registrar_service.find_student.assert_not_called()
    app.registrar_service.send_verification_code.assert_not_called()


@pytest.mark.asyncio
async def test_second_event_link_replaces_first_during_student_registration_without_new_code(app):
    await register(app)
    event = await app.event_repository.create(100, "Freshers Welcome")
    second = await app.event_repository.create(100, "Second Event")
    replies = await send(app, f"/start event_{event.id}", user_id=200)
    assert "Event saved: Freshers Welcome" in replies[0].text
    assert "own student ID" in replies[-1].text
    app.registrar_service.find_student.return_value = Student(
        "00000002", "Second Student", "second@example.test", account="00000002@example.test"
    )
    await send(app, "00000002", user_id=200)
    code = app.registrar_service.send_verification_code.await_args.args[1]
    emails = app.registrar_service.send_verification_code.await_count
    await send(app, f"/start event_{second.id}", user_id=200)
    assert await app.event_repository.pending_titles(200) == [second.title]
    assert app.registrar_service.send_verification_code.await_count == emails
    await send(app, code, user_id=200)
    async with app.database.transaction() as session:
        assert list(await session.scalars(select(EventRegistration))) == []
    replies = await send(
        app,
        user_id=200,
        contact=Contact(phone_number="+998909999999", first_name="Second", user_id=200),
    )
    assert "education level" in replies[-1].text
    async with app.database.transaction() as session:
        assert list(await session.scalars(select(EventRegistration))) == []
    replies = await choose_level(app, user_id=200, level="6")
    assert "Registration complete" in replies[-1].text and second.title in replies[-1].text
    async with app.database.transaction() as session:
        entry = (await session.scalars(select(EventRegistration))).one()
        assert entry.telegram_user_id == 200 and entry.event_id == second.id
        assert list(await session.scalars(select(PendingEventRegistration))) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", ["event_bad-id", "event_00000000-0000-4000-8000-000000000000"])
async def test_invalid_or_missing_event_does_not_start_registration(app, payload):
    replies = await send(app, "/start " + payload)
    assert "invalid" in replies[-1].text or "does not exist" in replies[-1].text
    app.registrar_service.find_student.assert_not_called()
    app.registrar_service.send_verification_code.assert_not_called()
    async with app.database.transaction() as session:
        assert list(await session.scalars(select(PendingEventRegistration))) == []


def methods(app, method_type):
    return [
        call.args[1]
        for call in app.bot.session.call_args_list
        if isinstance(call.args[1], method_type)
    ]


async def callback(
    app, data, *, user_id=100, chat_id=None, chat_type="private", photo=False, inaccessible=False
):
    message = {
        "message_id": 50,
        "date": datetime.now(timezone.utc),
        "chat": {"id": user_id if chat_id is None else chat_id, "type": chat_type},
        "text": "Members",
    }
    if photo:
        message.pop("text")
        message["photo"] = [
            {"file_id": "photo", "file_unique_id": "unique", "width": 360, "height": 360}
        ]
    query = {
        "id": "members-query",
        "from": {"id": user_id, "is_bot": False, "first_name": "User"},
        "chat_instance": "private",
        "data": data,
    }
    if inaccessible:
        query["inline_message_id"] = "unavailable-message"
    else:
        query["message"] = message
    await app.dp.feed_update(app.bot, Update(update_id=2, callback_query=query))


async def reach_education_step(app):
    await send(app, "00000001")
    await send(app, app.registrar_service.send_verification_code.await_args.args[1])
    return await send(
        app, contact=Contact(phone_number="+998901234567", first_name="User", user_id=100)
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "key,level", [("cifs", "CIFS"), ("4", "Level 4"), ("5", "Level 5"), ("6", "Level 6")]
)
async def test_inline_education_buttons_complete_registration(app, key, level):
    replies = await reach_education_step(app)
    assert "Registration complete" not in replies[-1].text
    replies = await choose_level(app, level=key)
    assert (
        "Registration complete" in replies[-1].text
        and f"Education level: {level}" in replies[-1].text
    )
    async with app.database.transaction() as session:
        assert (await session.get(StoredTelegramUser, 100)).education_level == level
    assert (await app.registration_repository.verified(100)).student_id == "00000001"


@pytest.mark.asyncio
async def test_education_step_reprompts_instead_of_lookup_email_or_another_phone_request(app):
    await reach_education_step(app)
    for text in ("/start", "/resend", "00000002", "Level 4", "New Event", "/unknown"):
        replies = await send(app, text)
        assert replies[-1].reply_markup.inline_keyboard[0][0].text == "CIFS"
        assert "Student <Name>" not in replies[-1].text
    assert app.registrar_service.find_student.await_count == 1
    assert app.registrar_service.send_verification_code.await_count == 1
    assert await app.registration_repository.verified(100) is None


@pytest.mark.asyncio
async def test_education_callback_requires_previous_steps_and_rejects_invalid_options(app):
    await callback(app, "education:4")
    assert "Confirm your email" in methods(app, AnswerCallbackQuery)[-1].text
    await reach_education_step(app)
    await callback(app, "education:7")
    assert "Choose CIFS" in methods(app, AnswerCallbackQuery)[-1].text
    await callback(app, "education:6", user_id=200)
    assert "Confirm your email" in methods(app, AnswerCallbackQuery)[-1].text
    assert await app.registration_repository.awaiting_education(100)
    assert await app.registration_repository.verified(100) is None


@pytest.mark.asyncio
async def test_removed_cancel_keeps_education_selection_available(app):
    await reach_education_step(app)
    replies = await send(app, "/cancel")
    assert replies[-1].reply_markup.inline_keyboard[0][0].text == "CIFS"
    assert await app.registration_repository.awaiting_education(100)
    await callback(app, "education:4")
    assert not await app.registration_repository.awaiting_education(100)
    assert await app.registration_repository.verified(100) is not None


@pytest.mark.asyncio
async def test_repeated_education_click_keeps_original_level(app):
    await register(app)
    await callback(app, "education:6")
    assert "already registered" in methods(app, AnswerCallbackQuery)[-1].text
    async with app.database.transaction() as session:
        assert (await session.get(StoredTelegramUser, 100)).education_level == "CIFS"


async def form_event(app, questions):
    from uuid import uuid4

    await register(app)
    event = await app.event_repository.create(100, "Event with questions")
    fields = {
        "title": event.title,
        "description": "Please answer a few questions.",
        "registration_open": True,
        "revision": event.revision,
        "response_retention_days": 30,
        "questions": [
            {
                "id": str(uuid4()),
                "label": label,
                "type": kind,
                "required": required,
                "options": ["Morning", "Evening"] if "choice" in kind else [],
            }
            for label, kind, required in questions
        ],
    }
    return await app.event_repository.configure(100, event.id, fields)


@pytest.mark.asyncio
async def test_event_survey_runs_in_chat_with_text_and_inline_mcq_before_enrollment(app):
    event = await form_event(
        app, [("Your team?", "text", True), ("Which session?", "single_choice", True)]
    )
    replies = await send(app, f"/start event_{event.id}")
    assert "Question 1/2" in replies[-1].text and "Your team?" in replies[-1].text
    assert "30 days" in replies[-1].text
    app.registrar_service.reset_mock()
    replies = await send(app, "My team")
    assert "Question 2/2" in replies[-1].text
    buttons = replies[-1].reply_markup.inline_keyboard
    assert [row[0].text for row in buttons] == ["Morning", "Evening"]
    assert (await app.event_repository.members(100, event.id)).total == 0
    await callback(app, buttons[1][0].callback_data)
    assert methods(app, SendMessage)[-1].text == "You are registered for: Event with questions"
    page = await app.event_repository.answer_page(100, event.id)
    assert page.members[0]["answers"] == {
        event.questions[0]["id"]: "My team",
        event.questions[1]["id"]: "Evening",
    }
    await callback(app, buttons[0][0].callback_data)
    assert methods(app, AnswerCallbackQuery)[-1].show_alert
    assert (await app.event_repository.members(100, event.id)).total == 1
    app.registrar_service.find_student.assert_not_called()
    app.registrar_service.send_verification_code.assert_not_called()


@pytest.mark.asyncio
async def test_new_student_enters_event_questions_only_after_full_account_registration(app):
    event = await form_event(app, [("Tell us something", "text", True)])
    await send(app, f"/start event_{event.id}", user_id=200)
    app.registrar_service.find_student.return_value = Student(
        "00000002", "Other", "other@example.test", account="00000002@example.test"
    )
    await send(app, "00000002", user_id=200)
    await send(app, app.registrar_service.send_verification_code.await_args.args[1], user_id=200)
    replies = await send(
        app,
        user_id=200,
        contact=Contact(phone_number="+998901234567", first_name="Other", user_id=200),
    )
    assert "education level" in replies[-1].text
    replies = await choose_level(app, user_id=200)
    assert "Question 1/1" in replies[-1].text
    assert await app.registration_repository.verified(200)
    assert (await app.event_repository.members(100, event.id)).total == 0
    await send(app, "Done", user_id=200)
    assert (await app.event_repository.members(100, event.id)).total == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy_button", [False, True])
async def test_choice_advances_immediately_and_optional_question_can_be_skipped(app, legacy_button):
    event = await form_event(
        app, [("Pick sessions", "multiple_choice", True), ("Any comment?", "text", False)]
    )
    replies = await send(app, f"/start event_{event.id}")
    assert "Choose one option below" in replies[-1].text
    choices = replies[-1].reply_markup.inline_keyboard
    assert [row[0].text for row in choices] == ["Morning", "Evening"]
    data = choices[0][0].callback_data
    await callback(app, data.replace(":choose:", ":toggle:") if legacy_button else data)
    assert methods(app, EditMessageReplyMarkup)[-1].reply_markup is None
    current = methods(app, SendMessage)[-1]
    assert "Any comment?" in current.text
    await callback(app, current.reply_markup.inline_keyboard[0][0].callback_data)
    assert (await app.event_repository.members(100, event.id)).total == 1


@pytest.mark.asyncio
async def test_me_does_not_consume_answers_or_reset_the_current_questionnaire(app):
    event = await form_event(app, [("First?", "text", True), ("Second?", "text", True)])
    await send(app, f"/start event_{event.id}")
    await send(app, "Partial answer")
    before = await app.event_survey.resume(100)
    app.registrar_service.reset_mock()
    replies = await send(app, "/me")
    assert PERSON.email in replies[-1].text
    after = await app.event_survey.resume(100)
    assert after.event.id == before.event.id and after.index == before.index
    assert after.answers == before.answers and after.token == before.token
    await send(app, "Final answer")
    assert (await app.event_repository.members(100, event.id)).total == 1
    app.registrar_service.find_student.assert_not_called()
    app.registrar_service.send_verification_code.assert_not_called()


@pytest.mark.asyncio
async def test_scanning_second_event_leaves_unfinished_first_questionnaire(app):
    first = await form_event(app, [("First answer?", "text", True), ("Next?", "text", True)])
    second = await app.event_repository.create(100, "Second event without questions")
    await send(app, f"/start event_{first.id}")
    await send(app, "Partial answer for the first event")
    replies = await send(app, f"/start event_{second.id}")
    assert "You are registered for" in replies[-1].text and second.title in replies[-1].text
    assert not await app.event_survey.active(100)
    assert await app.event_repository.pending_titles(100) == []
    assert (await app.event_repository.members(100, first.id)).total == 0
    assert (await app.event_repository.members(100, second.id)).total == 1
    await send(app, f"/start event_{first.id}")
    assert (await app.event_survey.resume(100)).index == 0


@pytest.mark.asyncio
async def test_removed_cancel_preserves_questionnaire_progress_and_verified_account(app):
    event = await form_event(app, [("First?", "text", True), ("Second?", "text", True)])
    await send(app, f"/start event_{event.id}")
    await send(app, "Partial")
    before = await app.event_survey.resume(100)
    replies = await send(app, "/cancel")
    assert "Second?" in replies[-1].text
    after = await app.event_survey.resume(100)
    assert after.index == before.index and after.answers == before.answers
    assert await app.event_survey.active(100)
    assert await app.registration_repository.verified(100)
    assert (await app.event_repository.members(100, event.id)).total == 0
    replies = await send(app, "Final answer")
    assert "You are registered for" in replies[-1].text
    assert (await app.event_repository.members(100, event.id)).total == 1


@pytest.mark.asyncio
async def test_panel_and_event_management_buttons_open_mini_app_only_for_organizers(app):
    app.dp["mini_app_url"] = "https://events.example.test"
    replies = await send(app, "/panel")
    assert "Complete registration" in replies[-1].text
    replies = await register(app)
    assert replies[-1].reply_markup is None
    replies = await send(app, "/panel")
    assert "/new_event" in replies[-1].text and replies[-1].reply_markup is None
    replies = await send(app, "/start")
    assert len(replies) == 1
    assert isinstance(replies[0].reply_markup, ReplyKeyboardRemove)
    replies = await send(app, "/help")
    assert "/panel" not in replies[-1].text
    replies = await send(app, "/new_event Welcome")
    button = replies[-1].reply_markup.inline_keyboard[-1][0]
    assert button.text == "Manage event" and button.web_app.url.startswith(
        app.dp["mini_app_url"] + "/?event="
    )
    replies = await send(app, "/panel")
    assert replies[-1].reply_markup.inline_keyboard[0][0].web_app.url == app.dp["mini_app_url"]
    replies = await send(app, "/start")
    assert len(replies) == 1
    assert isinstance(replies[0].reply_markup, ReplyKeyboardRemove)
    assert "Your verified profile" not in replies[0].text
    replies = await send(app, "/help")
    assert "/panel" in replies[-1].text


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["visitor", "student", "organizer"])
async def test_help_responds_with_commands_for_each_registration_role(app, role):
    app.dp["mini_app_url"] = "https://events.example.test"
    if role != "visitor":
        await register(app)
    if role == "organizer":
        await send(app, "/new_event Welcome")
    app.registrar_service.reset_mock()

    replies = await send(app, "/help")

    assert len(replies) == 1
    assert "/help" in replies[0].text and "/start" in replies[0].text
    assert ("/resend" in replies[0].text) == (role == "visitor")
    assert ("/panel" in replies[0].text) == (role == "organizer")
    assert ("/me" in replies[0].text) == (role != "visitor")
    app.registrar_service.find_student.assert_not_called()
    app.registrar_service.send_verification_code.assert_not_called()


@pytest.mark.asyncio
async def test_joining_an_event_does_not_unlock_the_mini_app(app):
    app.dp["mini_app_url"] = "https://events.example.test"
    await register(app)
    await send(app, "/new_event Welcome")
    async with app.database.transaction() as session:
        event = (await session.scalars(select(Event))).one()
    app.registrar_service.find_student.return_value = Student(
        "00000002", "Other", "other@example.test", account="00000002@example.test"
    )
    await register(app, user_id=200)
    replies = await send(app, f"/start event_{event.id}", user_id=200)
    assert "You are registered for" in replies[-1].text
    assert replies[-1].reply_markup is None
    replies = await send(
        app,
        contact=Contact(phone_number="+998901234567", first_name="Other", user_id=200),
        user_id=200,
    )
    assert replies[-1].reply_markup is None
    replies = await send(app, "/panel", user_id=200)
    assert "/new_event" in replies[-1].text and replies[-1].reply_markup is None


@pytest.mark.asyncio
@pytest.mark.parametrize("data", ["member_events:0", "members:00000000000040008000000000000001:0"])
@pytest.mark.parametrize("photo", [False, True])
async def test_retired_event_buttons_replace_old_keyboard_with_panel_only(app, data, photo):
    app.dp["mini_app_url"] = "https://events.example.test"
    await register(app)
    await app.event_repository.create(100, "Existing event")
    app.event_repository.members = AsyncMock(
        side_effect=AssertionError("Chat must not query participant records.")
    )
    app.registrar_service.reset_mock()
    await callback(app, data, photo=photo)
    keyboard = methods(app, EditMessageReplyMarkup)[-1].reply_markup
    assert [button.text for row in keyboard.inline_keyboard for button in row] == ["Event panel"]
    assert keyboard.inline_keyboard[0][0].web_app.url == app.dp["mini_app_url"]
    assert methods(app, SendRichMessage) == [] and methods(app, EditMessageText) == []
    app.event_repository.members.assert_not_called()
    app.registrar_service.find_student.assert_not_called()
    app.registrar_service.send_verification_code.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("registered", [False, True])
async def test_retired_buttons_do_not_unlock_panel_for_non_organizers(app, registered):
    app.dp["mini_app_url"] = "https://events.example.test"
    if registered:
        await register(app)
    await callback(app, "member_events:0")
    assert methods(app, AnswerCallbackQuery)[-1].show_alert
    assert methods(app, EditMessageReplyMarkup)[-1].reply_markup is None
    assert methods(app, SendRichMessage) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "options", [{"chat_type": "group"}, {"chat_id": 200}, {"inaccessible": True}]
)
async def test_retired_event_buttons_require_own_private_chat(app, options):
    await callback(app, "member_events:0", **options)
    assert "private chat" in methods(app, AnswerCallbackQuery)[-1].text
    assert methods(app, EditMessageReplyMarkup) == [] and methods(app, SendRichMessage) == []


@pytest.mark.asyncio
async def test_native_command_menu_follows_registration_and_event_creation(app):
    await send(app, "/start")
    current = methods(app, SetMyCommands)[-1]
    assert current.scope.chat_id == 100
    assert "resend" in [item.command for item in current.commands]
    assert "panel" not in [item.command for item in current.commands]
    await register(app)
    current = methods(app, SetMyCommands)[-1]
    names = [item.command for item in current.commands]
    assert {"new_event", "me"} <= set(names) and "resend" not in names and "panel" not in names
    app.dp["mini_app_url"] = "https://events.example.test"
    await send(app, "/new_event Welcome")
    assert "panel" in [item.command for item in methods(app, SetMyCommands)[-1].commands]
    count = len(methods(app, SetMyCommands))
    await send(app, "/help")
    assert len(methods(app, SetMyCommands)) == count
