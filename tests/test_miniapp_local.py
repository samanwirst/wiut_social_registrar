from datetime import datetime, timedelta, timezone
from ipaddress import ip_address
import socket
import ssl
from unittest.mock import AsyncMock

from aiohttp import ClientSession
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import pytest

from app.bot import BotApp
from app.event_repository import EventRepository
from app.miniapp import MiniAppServer, mini_app_ssl_context
from config import BotSettings
from registrar.config import ConfigurationError, Settings

TOKEN = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789"


@pytest.mark.asyncio
@pytest.mark.parametrize("use_test", [False, True])
async def test_bot_selects_aiogram_official_test_endpoint_only_when_enabled(tmp_path, monkeypatch, use_test):
    monkeypatch.setattr("app.bot.RegistrarService", lambda _: AsyncMock())
    settings = BotSettings(TOKEN, Settings(tmp_path / ".env"), verification_secret="ab" * 32,
                           telegram_test_environment=use_test)
    app = BotApp(settings)
    try:
        path = app.bot.session.api.api_url("test-token", "getMe")
        assert path == f"https://api.telegram.org/bottest-token/{'test/' if use_test else ''}getMe"
        assert app.database.engine.url.database.endswith(
            "registrations.telegram-test.sqlite3" if use_test else "registrations.sqlite3")
    finally:
        await app.shutdown()


@pytest.fixture
def local_certificate(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(timezone.utc)
    certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.IPAddress(ip_address("127.0.0.1"))]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True).sign(key, hashes.SHA256()))
    cert_file, key_file = tmp_path / "localhost.pem", tmp_path / "localhost-key.pem"
    cert_file.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    key_file.chmod(0o600)
    return cert_file, key_file


@pytest.mark.asyncio
async def test_native_local_https_works_with_a_trusted_client_and_keeps_api_auth(repository, local_certificate):
    cert_file, key_file = local_certificate
    settings = BotSettings(TOKEN, Settings(cert_file.parent / ".env"), mini_app_url="https://127.0.0.1",
        mini_app_port=0, mini_app_tls_cert_file=cert_file, mini_app_tls_key_file=key_file)
    bot = AsyncMock()
    bot.token = TOKEN
    server = MiniAppServer(EventRepository(repository.db, clock=repository.clock), bot, settings)
    try:
        await server.start()
        port = server.runner.addresses[0][1]
        trusted_context = ssl.create_default_context(cafile=str(cert_file))
        async with ClientSession() as client:
            response = await client.get(f"https://127.0.0.1:{port}/health", ssl=trusted_context)
            assert response.status == 200 and (await response.json())["status"] == "ok"
            response = await client.get(f"https://127.0.0.1:{port}/api/session", ssl=trusted_context)
            assert response.status == 401
    finally:
        await server.close()


def test_missing_or_invalid_certificates_fail_without_prompting_or_exposing_key_contents(tmp_path):
    settings = BotSettings(TOKEN, Settings(tmp_path / ".env"), mini_app_tls_cert_file=tmp_path / "cert.pem",
                           mini_app_tls_key_file=tmp_path / "key.pem")
    with pytest.raises(ConfigurationError, match="Could not load"):
        mini_app_ssl_context(settings)
    (tmp_path / "cert.pem").write_text("invalid-certificate")
    (tmp_path / "key.pem").write_text("private-test-key-content")
    with pytest.raises(ConfigurationError) as error:
        mini_app_ssl_context(settings)
    assert "private-test-key-content" not in str(error.value)


@pytest.mark.asyncio
async def test_occupied_port_reports_the_cause_and_cleans_up_background_tasks(repository, tmp_path):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        settings = BotSettings(TOKEN, Settings(tmp_path / ".env"), mini_app_url="http://127.0.0.1",
                               mini_app_port=port, telegram_test_environment=True)
        server = MiniAppServer(EventRepository(repository.db, clock=repository.clock), AsyncMock(), settings)
        try:
            with pytest.raises(ConfigurationError, match=f"port {port} is already in use"):
                await server.start()
            assert server.cleanup_task.done()
            assert not server.runner.addresses
        finally:
            await server.close()


@pytest.mark.asyncio
async def test_missing_frontend_build_has_actionable_startup_error(repository, tmp_path, monkeypatch):
    monkeypatch.setattr("app.miniapp.STATIC", tmp_path / "missing-frontend")
    settings = BotSettings(TOKEN, Settings(tmp_path / ".env"), mini_app_url="https://127.0.0.1")
    server = MiniAppServer(EventRepository(repository.db), AsyncMock(), settings)
    try:
        with pytest.raises(ConfigurationError, match="npm run build --prefix frontend"):
            await server.start()
        assert server.runner is None and server.cleanup_task is None
    finally:
        await server.close()
