import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from aiogram.methods import GetMe, GetUpdates

import main
from app.bot import BotApp
from app.miniapp.assets import ready
from app.miniapp.state import HEALTH
from app.services import runtime_health
from app.services.runtime_health import RuntimeHealth
from config import BotSettings
from monitoring.state import read_json
from registrar.config import Settings
from registrar.errors import AuthenticationError
from tests.helpers import TEST_TOKEN


async def until(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0.001)


@pytest.mark.asyncio
async def test_outlook_auth_failure_does_not_stop_heartbeat_or_database_and_can_recover(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(runtime_health, "OUTLOOK_RETRY", 0.001)
    database, registrar = AsyncMock(), AsyncMock()
    registrar.check_connection.side_effect = [AuthenticationError("private-auth-token"), None]
    path = tmp_path / "health.json"
    health = RuntimeHealth(database, registrar, path)
    try:
        await health.start()
        await until(lambda: registrar.check_connection.await_count >= 2)
        await until(lambda: health.components.get("outlook", {}).get("ok"))
        assert health.components["database"]["ok"]
    finally:
        await health.close()
        await health.close()
    assert read_json(path)["phase"] == "stopped"
    assert "private-auth-token" not in path.read_text()
    assert not health.tasks


@pytest.mark.asyncio
async def test_slow_graph_probe_is_never_enqueued_twice(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_health, "OUTLOOK_RETRY", 0.001)
    monkeypatch.setattr(runtime_health, "OUTLOOK_TIMEOUT", 0.005)
    release = asyncio.Event()
    registrar = SimpleNamespace(check_connection=AsyncMock(side_effect=release.wait))
    health = RuntimeHealth(AsyncMock(), registrar, tmp_path / "health.json")
    try:
        await health.start()
        await until(lambda: health.components.get("outlook", {}).get("ok") is False)
        await asyncio.sleep(0.03)
        registrar.check_connection.assert_awaited_once()
        release.set()
        await until(lambda: health.components["outlook"]["ok"])
    finally:
        await health.close()


@pytest.mark.asyncio
async def test_polling_heartbeat_observes_empty_updates_failure_and_recovery(tmp_path):
    health = RuntimeHealth(None, None, tmp_path / "health.json")
    transport = AsyncMock(return_value=[])
    assert await health.polling_request(transport, None, GetUpdates()) == []
    assert health.components["polling"]["ok"]
    transport.side_effect = OSError("private-url-token")
    with pytest.raises(OSError):
        await health.polling_request(transport, None, GetUpdates())
    assert health.components["polling"]["reason"] == "OSError"
    transport.side_effect = None
    await health.polling_request(transport, None, GetMe())
    assert health.components["polling"]["ok"] is False
    await health.polling_request(transport, None, GetUpdates())
    assert health.components["polling"]["ok"]
    assert "private-url" not in json.dumps(health.snapshot())


@pytest.mark.asyncio
async def test_fatal_startup_state_is_saved_even_before_workers_start(tmp_path):
    path = tmp_path / "health.json"
    health = RuntimeHealth(None, None, path)
    health.phase = "failed"
    health.incident("fatal", RuntimeError("private-student-and-token"))
    await health.close()
    assert read_json(path)["phase"] == "failed"
    assert read_json(path)["incidents"]["fatal:RuntimeError"]["count"] == 1
    assert "private" not in path.read_text()


@pytest.mark.asyncio
async def test_normal_startup_defers_outlook_but_explicit_check_is_strict(tmp_path, monkeypatch):
    app = SimpleNamespace(
        check_connection=AsyncMock(return_value=SimpleNamespace(username="test_bot")),
        run=AsyncMock(),
        shutdown=AsyncMock(),
    )
    monkeypatch.setattr(main, "BotApp", Mock(return_value=app))
    settings = SimpleNamespace(telegram_test_environment=False)
    await main.run(settings)
    app.check_connection.assert_awaited_once_with(strict_outlook=False)
    app.run.assert_awaited_once()
    app.check_connection.reset_mock()
    app.run.reset_mock()
    await main.run(settings, check=True)
    app.check_connection.assert_awaited_once_with(strict_outlook=True)
    app.run.assert_not_awaited()


@pytest.mark.asyncio
async def test_connection_can_validate_database_and_telegram_without_graph(tmp_path, monkeypatch):
    registrar = AsyncMock()
    registrar.check_connection.side_effect = AuthenticationError("Sign in required")
    monkeypatch.setattr("app.bot.RegistrarService", lambda _: registrar)
    app = BotApp(
        BotSettings(TEST_TOKEN, Settings(tmp_path / ".env"), verification_secret="ab" * 32)
    )
    app.bot.get_me = AsyncMock(return_value=SimpleNamespace(username="test_bot"))
    try:
        assert (await app.check_connection(strict_outlook=False)).username == "test_bot"
        registrar.check_connection.assert_not_awaited()
        with pytest.raises(AuthenticationError):
            await app.check_connection()
        await app.database.ping()
    finally:
        await app.shutdown()


@pytest.mark.asyncio
async def test_readiness_excludes_outlook_but_requires_database_and_live_polling(tmp_path):
    monitor = RuntimeHealth(None, None, tmp_path / "health.json")
    request = SimpleNamespace(app={HEALTH: monitor})
    assert (await ready(request)).status == 503
    monitor.report("database", True)
    monitor.report("polling", True)
    monitor.report("outlook", False, "AuthenticationError")
    assert (await ready(request)).status == 200
    monitor.report("database", False, "TimeoutError")
    assert (await ready(request)).status == 503


def test_unexpected_startup_failure_is_logged_without_its_sensitive_message(monkeypatch, caplog):
    monkeypatch.setattr(
        main.BotSettings, "load", Mock(side_effect=RuntimeError("private-token-and-record"))
    )
    assert main.main([]) == 2
    assert "Unexpected application failure (RuntimeError)" in caplog.text
    assert "private-token-and-record" not in caplog.text
