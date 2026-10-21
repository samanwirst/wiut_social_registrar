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

    def find(student_id, *, refresh=False):
        threads.append(threading.get_ident())
        return Student(student_id, "Student", "student@example.test")

    client.find_student.side_effect = find
    client.close.side_effect = lambda: threads.append(threading.get_ident())
    monkeypatch.setattr("app.services.registrar_service.GraphClient", Mock(return_value=client))
    service = RegistrarService(Settings(tmp_path / ".env"))
    try:
        students = await asyncio.gather(
            service.find_student("00000001"), service.find_student("00000002")
        )
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


def test_local_defaults_to_private_sqlite_and_persistent_secret(tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    path = tmp_path / ".env"
    path.write_text("TELEGRAM_BOT_TOKEN=123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789\n")
    first = BotSettings.load(path)
    second = BotSettings.load(path)
    assert first.database_url.startswith("sqlite+aiosqlite:///")
    assert first.verification_secret == second.verification_secret
    assert len(first.verification_secret) == 64
    assert first.verification_secret not in repr(first)
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "extra",
    [
        "APP_ENV=invalid",
        "APP_ENV=production",
        "APP_ENV=production\nDATABASE_URL=sqlite+aiosqlite:///test.sqlite3",
        "DATABASE_URL=invalid",
    ],
)
def test_invalid_database_configuration_is_rejected(tmp_path, extra):
    path = tmp_path / ".env"
    path.write_text("TELEGRAM_BOT_TOKEN=123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789\n" + extra)
    with pytest.raises(ConfigurationError):
        BotSettings.load(path)


def test_production_builds_postgres_url_without_losing_special_password_characters(tmp_path):
    from sqlalchemy.engine import make_url

    path = tmp_path / ".env"
    path.write_text(
        "TELEGRAM_BOT_TOKEN=123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789\n"
        "APP_ENV=production\nPOSTGRES_PASSWORD='private@password/with:symbols'\n"
    )
    settings = BotSettings.load(path)
    url = make_url(settings.database_url)
    assert url.drivername == "postgresql+asyncpg" and url.host == "postgres"
    assert url.password == "private@password/with:symbols"
    assert "private" not in repr(settings)


@pytest.mark.parametrize(
    "extra",
    [
        "MINI_APP_URL=http://example.test",
        "MINI_APP_URL=https://example.test/path",
        "MINI_APP_URL=https://user:password@example.test",
        "MINI_APP_URL=https://example.test?token=secret",
        "MINI_APP_URL=https://[invalid",
        "MINI_APP_URL=https://example.test:invalid",
        "MINI_APP_PORT=0",
        "MINI_APP_PORT=70000",
    ],
)
def test_invalid_mini_app_configuration_is_rejected(tmp_path, extra):
    path = tmp_path / ".env"
    path.write_text("TELEGRAM_BOT_TOKEN=123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789\n" + extra)
    with pytest.raises(ConfigurationError):
        BotSettings.load(path)


def test_mini_app_configuration_uses_https_origin_and_local_bind_by_default(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "TELEGRAM_BOT_TOKEN=123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789\nMINI_APP_URL=https://events.example.test/\n"
    )
    settings = BotSettings.load(path)
    assert settings.mini_app_url == "https://events.example.test"
    assert settings.mini_app_host == "127.0.0.1" and settings.mini_app_port == 8080


def test_official_test_environment_allows_http_and_uses_a_separate_default_database(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "TELEGRAM_BOT_TOKEN=123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789\n"
        "TELEGRAM_TEST_ENVIRONMENT=true\nMINI_APP_URL=http://127.0.0.1:8080\n"
    )
    settings = BotSettings.load(path)
    assert settings.telegram_test_environment
    assert settings.mini_app_url == "http://127.0.0.1:8080"
    assert settings.database_url.endswith("registrations.telegram-test.sqlite3")


@pytest.mark.parametrize(
    "extra",
    [
        "TELEGRAM_TEST_ENVIRONMENT=invalid",
        "TELEGRAM_TEST_ENVIRONMENT=true\nAPP_ENV=production\nPOSTGRES_PASSWORD=test-password",
        "MINI_APP_URL=https://127.0.0.1:8443\nMINI_APP_TLS_CERT_FILE=cert.pem",
        "MINI_APP_TLS_KEY_FILE=key.pem",
        "MINI_APP_TLS_CERT_FILE=cert.pem\nMINI_APP_TLS_KEY_FILE=key.pem",
        "TELEGRAM_TEST_ENVIRONMENT=true\nMINI_APP_URL=http://127.0.0.1:8080\nMINI_APP_TLS_CERT_FILE=cert.pem\nMINI_APP_TLS_KEY_FILE=key.pem",
    ],
)
def test_unsafe_or_incomplete_test_and_tls_configuration_is_rejected(tmp_path, extra):
    path = tmp_path / ".env"
    path.write_text("TELEGRAM_BOT_TOKEN=123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789\n" + extra)
    with pytest.raises(ConfigurationError):
        BotSettings.load(path)


def test_local_tls_paths_are_resolved_from_env_file_location(tmp_path):
    directory = tmp_path / "private"
    directory.mkdir()
    path = directory / ".env"
    path.write_text(
        "TELEGRAM_BOT_TOKEN=123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789\n"
        "MINI_APP_URL=https://127.0.0.1:8443\nMINI_APP_PORT=8443\n"
        "MINI_APP_TLS_CERT_FILE=certificates/localhost.pem\nMINI_APP_TLS_KEY_FILE=certificates/localhost-key.pem\n"
    )
    settings = BotSettings.load(path)
    assert settings.mini_app_tls_cert_file == directory / "certificates" / "localhost.pem"
    assert settings.mini_app_tls_key_file == directory / "certificates" / "localhost-key.pem"
    assert not settings.telegram_test_environment


@pytest.mark.asyncio
async def test_verification_email_uses_fixed_template_in_graph_worker(monkeypatch, tmp_path):
    client = Mock()
    monkeypatch.setattr("app.services.registrar_service.GraphClient", Mock(return_value=client))
    service = RegistrarService(Settings(tmp_path / ".env"))
    student = Student(
        "00000001", "Student", "student@example.test", account="00000001@example.test"
    )
    try:
        await service.send_verification_code(student, "001234", 600)
    finally:
        await service.close()
    recipient, subject, body = client.send_email.call_args.args
    assert recipient.email == student.email
    assert subject == "WIUT Social Registrar verification code"
    assert "001234" in body and "10 minutes" in body
    client.send_email.assert_called_once()
