import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.bot import BotApp
from app.services.answer_cleanup import AnswerCleanup
from config import BotSettings
from registrar.config import Settings
from tests.helpers import TEST_TOKEN


@pytest.mark.asyncio
async def test_retention_retries_safely_and_close_cancels_the_worker(caplog):
    recovered = asyncio.Event()
    calls = 0

    async def purge():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise SQLAlchemyError("private-answer-and-connection-details")
        if calls >= 3:
            recovered.set()

    repository = SimpleNamespace(purge_answers=purge)
    cleanup = AnswerCleanup(repository, interval=0)
    try:
        await cleanup.start()
        task = cleanup.task
        await asyncio.wait_for(recovered.wait(), timeout=2)
    finally:
        await cleanup.close()
        await cleanup.close()
    assert task.done() and cleanup.task is None
    assert "will retry" in caplog.text
    assert "private-answer-and-connection-details" not in caplog.text


@pytest.mark.asyncio
async def test_failed_initial_retention_does_not_leave_a_background_task():
    repository = AsyncMock()
    repository.purge_answers.side_effect = SQLAlchemyError("unavailable")
    cleanup = AnswerCleanup(repository)
    with pytest.raises(SQLAlchemyError):
        await cleanup.start()
    assert cleanup.task is None
    await cleanup.close()


@pytest.mark.asyncio
async def test_bot_runs_retention_when_the_mini_app_is_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr("app.bot.RegistrarService", lambda _: AsyncMock())
    app = BotApp(
        BotSettings(TEST_TOKEN, Settings(tmp_path / ".env"), verification_secret="ab" * 32)
    )
    app.bot.get_webhook_info = AsyncMock(return_value=SimpleNamespace(url=""))
    app.dp.start_polling = AsyncMock()
    app.command_menu.install_defaults = AsyncMock()
    try:
        await app.database.migrate()
        await app.run()
        task = app.answer_cleanup.task
        assert task is not None and not task.done()
        assert app.miniapp_server.runner is None
        app.dp.start_polling.assert_awaited_once()
    finally:
        await app.shutdown()
    assert task.done()


@pytest.mark.asyncio
async def test_shutdown_closes_other_resources_even_if_one_close_fails(tmp_path, monkeypatch):
    registrar = AsyncMock()
    monkeypatch.setattr("app.bot.RegistrarService", lambda _: registrar)
    app = BotApp(
        BotSettings(TEST_TOKEN, Settings(tmp_path / ".env"), verification_secret="ab" * 32)
    )
    app.miniapp_server.close = AsyncMock(side_effect=RuntimeError("web shutdown failed"))
    app.answer_cleanup.close = AsyncMock()
    other_resources = (app.database, app.dp.storage, app.bot.session)
    for resource in other_resources:
        resource.close = AsyncMock(wraps=resource.close)
    try:
        with pytest.raises(RuntimeError, match="web shutdown failed"):
            await app.shutdown()
        app.answer_cleanup.close.assert_awaited_once()
        registrar.close.assert_awaited_once()
        for resource in other_resources:
            resource.close.assert_awaited_once()
    finally:
        app.miniapp_server.close.side_effect = None
        await app.shutdown()
