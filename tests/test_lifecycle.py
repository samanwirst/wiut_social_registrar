import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.types import Chat, Message, Update, User
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
async def test_failed_initial_retention_keeps_a_retry_worker_instead_of_aborting_startup():
    repository = AsyncMock()
    repository.purge_answers.side_effect = SQLAlchemyError("unavailable")
    cleanup = AnswerCleanup(repository)
    await cleanup.start()
    assert cleanup.task is not None and not cleanup.task.done()
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
        broadcast_task = app.broadcast_worker.task
        assert task is not None and not task.done()
        assert broadcast_task is not None and not broadcast_task.done()
        assert app.miniapp_server.runner is None
        app.dp.start_polling.assert_awaited_once()
    finally:
        await app.shutdown()
    assert task.done()
    assert broadcast_task.done() and app.broadcast_worker.task is None


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


@pytest.mark.asyncio
async def test_shutdown_drains_active_and_same_user_queued_updates_before_closing_clients(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("app.bot.RegistrarService", lambda _: AsyncMock())
    app = BotApp(
        BotSettings(TEST_TOKEN, Settings(tmp_path / ".env"), verification_secret="ab" * 32)
    )
    entered = [asyncio.Event(), asyncio.Event()]
    release = [asyncio.Event(), asyncio.Event()]
    tasks = []

    async def pause(handler, update, data):
        index = update.update_id - 1
        entered[index].set()
        await release[index].wait()
        return await handler(update, data)

    app.dp.update.outer_middleware(pause)
    try:
        await app.database.migrate()
        await app.bot.session.close()
        app.bot.session = AsyncMock()
        app.database.close = AsyncMock(wraps=app.database.close)
        for number in (1, 2):
            update = Update(
                update_id=number,
                message=Message(
                    message_id=number,
                    date=datetime.now(timezone.utc),
                    chat=Chat(id=100, type="private"),
                    from_user=User(id=100, is_bot=False, first_name="Student"),
                    text="/help",
                ),
            )
            tasks.append(asyncio.create_task(app.dp.feed_update(app.bot, update)))
            if number == 1:
                await asyncio.wait_for(entered[0].wait(), timeout=2)
        tasks.append(asyncio.create_task(app.shutdown()))
        await asyncio.sleep(0)
        assert not tasks[-1].done()
        app.database.close.assert_not_awaited()
        release[0].set()
        await asyncio.wait_for(entered[1].wait(), timeout=2)
        assert not tasks[-1].done()
        app.database.close.assert_not_awaited()
        app.bot.session.close.assert_not_awaited()
        release[1].set()
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=2)
        app.database.close.assert_awaited_once()
        app.bot.session.close.assert_awaited_once()
        app.registrar_service.find_student.assert_not_called()
    finally:
        for barrier in release:
            barrier.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await app.shutdown()
