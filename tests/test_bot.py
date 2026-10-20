from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message, Update, User

from app.bot import BotApp
from config import BotSettings
from registrar.config import Settings
from registrar.errors import GraphError
from registrar.models import Student

TEST_TOKEN = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789"


@pytest_asyncio.fixture
async def app(monkeypatch, tmp_path):
    service = AsyncMock()
    service.find_student.return_value = Student("00000001", "Student <Name>", "student@example.test", account="00000001@example.test")
    monkeypatch.setattr("app.bot.RegistrarService", lambda _: service)
    instance = BotApp(BotSettings(TEST_TOKEN, Settings(tmp_path / ".env")))
    await instance.bot.session.close()
    instance.bot.session = AsyncMock()
    try:
        yield instance
    finally:
        await instance.shutdown()


async def send(app, text, *, user_id=100):
    update = Update(update_id=1, message=Message(
        message_id=1, date=datetime.now(timezone.utc), chat=Chat(id=user_id, type="private"),
        from_user=User(id=user_id, is_bot=False, first_name="User"), text=text,
    ))
    await app.dp.feed_update(app.bot, update)
    return [call.args[1] for call in app.bot.session.call_args_list if isinstance(call.args[1], SendMessage)]


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["/start", "/help", "/find"])
async def test_instructions_do_not_use_graph(app, text):
    replies = await send(app, text)
    assert replies
    app.registrar_service.find_student.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("user_id", [100, 200])
@pytest.mark.parametrize("text", ["00000001", "/find 00000001"])
async def test_lookup_is_public_and_preserves_leading_zeroes(app, text, user_id):
    replies = await send(app, text, user_id=user_id)
    app.registrar_service.find_student.assert_awaited_once_with("00000001")
    assert "Name: Student <Name>" in replies[-1].text
    assert "Email: student@example.test" in replies[-1].text
    assert replies[-1].parse_mode is None


@pytest.mark.asyncio
async def test_missing_student(app):
    app.registrar_service.find_student.return_value = None
    replies = await send(app, "99999999")
    assert replies[-1].text == "No student found with this ID."


@pytest.mark.asyncio
async def test_validation_error_is_shown_to_user(app):
    app.registrar_service.find_student.side_effect = ValueError("Student ID must contain 1 to 32 digits.")
    replies = await send(app, "bad-id")
    assert "1 to 32 digits" in replies[-1].text


@pytest.mark.asyncio
async def test_graph_error_hides_host_configuration(app):
    app.registrar_service.find_student.side_effect = GraphError("Run cli.py --login on the host.")
    replies = await send(app, "00000001")
    assert "temporarily unavailable" in replies[-1].text
    assert "cli.py" not in replies[-1].text


@pytest.mark.asyncio
async def test_unexpected_error_hides_exception_and_recovers(app, caplog):
    app.registrar_service.find_student.side_effect = RuntimeError("private-token-in-url")
    replies = await send(app, "00000001")
    assert "Something went wrong" in replies[-1].text
    assert "private-token-in-url" not in caplog.text
    assert "private-token-in-url" not in replies[-1].text


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["/send", "/mail 00000001", "/send_email 00000001"])
async def test_bot_has_no_email_commands(app, text):
    replies = await send(app, text)
    assert "student ID" in replies[-1].text
    assert app.registrar_service.mock_calls == []
    assert app.dp.resolve_used_update_types() == ["message"]


@pytest.mark.asyncio
async def test_no_email_callback_is_handled(app):
    update = Update(update_id=1, callback_query={
        "id": "old-button", "from": {"id": 100, "is_bot": False, "first_name": "User"},
        "chat_instance": "private", "data": "send:00000001",
    })
    await app.dp.feed_update(app.bot, update)
    assert app.registrar_service.mock_calls == []
    app.bot.session.assert_not_called()
