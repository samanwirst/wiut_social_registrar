import asyncio
import threading
from unittest.mock import Mock

import pytest

from app.services.registrar_service import RegistrarService
from config import BotSettings
from registrar.config import ConfigurationError, Settings
from registrar.models import Student


@pytest.mark.asyncio
async def test_graph_calls_and_cleanup_share_one_background_thread(monkeypatch, tmp_path):
    threads = []
    client = Mock()

    def find(student_id):
        threads.append(threading.get_ident())
        return Student(student_id, "Student", "student@example.test")

    client.find_student.side_effect = find
    client.close.side_effect = lambda: threads.append(threading.get_ident())
    monkeypatch.setattr("app.services.registrar_service.GraphClient", Mock(return_value=client))
    service = RegistrarService(Settings(tmp_path / ".env"))
    try:
        students = await asyncio.gather(service.find_student("00000001"), service.find_student("00000002"))
        assert [student.student_id for student in students] == ["00000001", "00000002"]
    finally:
        await service.close()
    assert len(threads) == 3
    assert len(set(threads)) == 1
    assert threads[0] != threading.get_ident()
    client.send_email.assert_not_called()
    await service.close()
    client.close.assert_called_once()


@pytest.mark.asyncio
async def test_invalid_ids_never_reach_graph(monkeypatch, tmp_path):
    client = Mock()
    monkeypatch.setattr("app.services.registrar_service.GraphClient", Mock(return_value=client))
    service = RegistrarService(Settings(tmp_path / ".env"))
    try:
        for student_id in ("", "bad-id", "1' OR 1=1", "123@other.test"):
            with pytest.raises(ValueError):
                await service.find_student(student_id)
        client.find_student.assert_not_called()
    finally:
        await service.close()


@pytest.mark.parametrize("token", ["", "secret-invalid-token"])
def test_invalid_bot_token_is_not_exposed(tmp_path, monkeypatch, token):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    path = tmp_path / ".env"
    path.write_text("TELEGRAM_BOT_TOKEN=" + token)
    with pytest.raises(ConfigurationError) as error:
        BotSettings.load(path)
    assert "secret-invalid-token" not in str(error.value)


def test_bot_settings_do_not_expose_credentials_in_repr(tmp_path, monkeypatch):
    token = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789"
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    path = tmp_path / ".env"
    path.write_text("TELEGRAM_BOT_TOKEN=" + token)
    settings = BotSettings.load(path)
    assert settings.token == token
    assert token not in repr(settings)
