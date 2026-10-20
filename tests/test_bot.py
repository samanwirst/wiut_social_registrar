import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from aiogram.methods import SendMessage
from aiogram.types import Chat, Contact, Message, ReplyKeyboardRemove, Update, User

from app.bot import BotApp
from config import BotSettings
from registrar.config import Settings
from registrar.errors import GraphError, SendStatusUnknown
from registrar.models import Student

TEST_TOKEN = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789"
PERSON = Student("00000001", "Student <Name>", "student@example.test", account="00000001@example.test",
                 graph_id="00000000-0000-0000-0000-000000000001", given_name="Student", surname="Name")


@pytest_asyncio.fixture
async def app(monkeypatch, tmp_path):
    service = AsyncMock()
    service.find_student.return_value = PERSON
    monkeypatch.setattr("app.bot.RegistrarService", lambda _: service)
    instance = BotApp(BotSettings(TEST_TOKEN, Settings(tmp_path / ".env"), verification_secret="ab" * 32))
    await instance.database.migrate()
    await instance.bot.session.close()
    instance.bot.session = AsyncMock()
    try:
        yield instance
    finally:
        await instance.shutdown()


async def send(app, text=None, *, user_id=100, chat_type="private", contact=None, **message_fields):
    update = Update(update_id=1, message=Message(
        message_id=1, date=datetime.now(timezone.utc), chat=Chat(id=user_id, type=chat_type),
        from_user=User(id=user_id, is_bot=False, first_name="User", username="test_user", language_code="en"),
        text=text, contact=contact, **message_fields,
    ))
    before = len(app.bot.session.call_args_list)
    await app.dp.feed_update(app.bot, update)
    return [call.args[1] for call in app.bot.session.call_args_list[before:] if isinstance(call.args[1], SendMessage)]


async def register(app, user_id=100):
    await send(app, "00000001", user_id=user_id)
    code = app.registrar_service.send_verification_code.await_args.args[1]
    await send(app, code, user_id=user_id)
    return await send(app, user_id=user_id,
                      contact=Contact(phone_number="+998901234567", first_name="User", user_id=user_id))


@pytest.mark.asyncio
async def test_registration_hides_profile_until_email_is_verified_and_own_phone_is_shared(app):
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
    replies = await send(app, contact=Contact(phone_number="+998901234567", first_name="User", user_id=100))
    assert "Registration complete" in replies[-1].text
    assert "Name: Student <Name>" in replies[-1].text
    assert replies[-1].parse_mode is None
    assert isinstance(replies[-1].reply_markup, ReplyKeyboardRemove)
    assert (await app.registration_repository.verified(100)).student_id == "00000001"
    replies = await send(app, "/start")
    assert "Your verified profile" in replies[-1].text
    assert app.registrar_service.send_verification_code.await_count == 1


@pytest.mark.asyncio
async def test_verified_user_can_still_look_up_students(app):
    await register(app)
    replies = await send(app, "00000001")
    assert "Email: student@example.test" in replies[-1].text
    assert app.registrar_service.send_verification_code.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["/find", "/find 00000001", "/send", "/mail 00000001"])
async def test_removed_commands_cannot_look_up_or_send(app, text):
    replies = await send(app, text)
    assert "student ID" in replies[-1].text
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
    replies = await send(app, contact=Contact(phone_number="+998901234567", first_name="User", user_id=100))
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
async def test_cancel_invalidates_code_without_resetting_cooldown(app):
    await send(app, "00000001")
    await send(app, "/cancel")
    assert await app.registration_repository.pending(100) is None
    replies = await send(app, "00000001")
    assert "wait" in replies[-1].text
    assert await app.registration_repository.verified(100) is None


@pytest.mark.asyncio
async def test_unexpected_error_never_logs_private_exception_text(app, caplog):
    app.registrar_service.find_student.side_effect = RuntimeError("private-token-in-url")
    replies = await send(app, "00000001")
    assert "Something went wrong" in replies[-1].text
    assert "private-token-in-url" not in caplog.text


@pytest.mark.asyncio
async def test_old_email_callback_is_not_handled(app):
    update = Update(update_id=1, callback_query={
        "id": "old-button", "from": {"id": 100, "is_bot": False, "first_name": "User"},
        "chat_instance": "private", "data": "send:00000001",
    })
    await app.dp.feed_update(app.bot, update)
    app.registrar_service.send_verification_code.assert_not_called()
    app.bot.session.assert_not_called()


@pytest.mark.asyncio
async def test_contact_before_code_verification_does_not_register(app):
    await send(app, "00000001")
    replies = await send(app, contact=Contact(phone_number="+998901234567", first_name="User", user_id=100))
    assert "Verify your Outlook email first" in replies[-1].text
    assert await app.registration_repository.verified(100) is None
    assert await app.registration_repository.pending(100) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("contact_user_id", [None, 200])
async def test_foreign_or_unidentified_contact_is_rejected(app, contact_user_id):
    await send(app, "00000001")
    code = app.registrar_service.send_verification_code.await_args.args[1]
    await send(app, code)
    replies = await send(app, contact=Contact(phone_number="+998901234567", first_name="Other", user_id=contact_user_id))
    assert "your own Telegram contact" in replies[-1].text
    assert replies[-1].reply_markup.keyboard[0][0].request_contact
    assert await app.registration_repository.verified(100) is None


@pytest.mark.asyncio
async def test_forwarded_contact_is_rejected(app):
    await send(app, "00000001")
    await send(app, app.registrar_service.send_verification_code.await_args.args[1])
    replies = await send(app, contact=Contact(phone_number="+998901234567", first_name="User", user_id=100),
                         forward_origin={"type": "user", "date": datetime.now(timezone.utc),
                                         "sender_user": {"id": 100, "is_bot": False, "first_name": "User"}})
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
async def test_cancel_phone_step_removes_keyboard_and_requires_email_again(app):
    await send(app, "00000001")
    await send(app, app.registrar_service.send_verification_code.await_args.args[1])
    replies = await send(app, "/cancel")
    assert isinstance(replies[-1].reply_markup, ReplyKeyboardRemove)
    assert not await app.registration_repository.awaiting_phone(100)
    replies = await send(app, contact=Contact(phone_number="+998901234567", first_name="User", user_id=100))
    assert "Verify your Outlook email first" in replies[-1].text
    assert await app.registration_repository.verified(100) is None


@pytest.mark.asyncio
async def test_repeated_contact_does_not_repeat_registration(app):
    await register(app)
    replies = await send(app, contact=Contact(phone_number="+998909999999", first_name="User", user_id=100))
    assert "already registered" in replies[-1].text
    assert isinstance(replies[-1].reply_markup, ReplyKeyboardRemove)
