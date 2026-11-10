import asyncio
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError, TelegramRetryAfter
from aiogram.methods import SendDocument
from openpyxl import load_workbook
from PIL import Image

from app.event_errors import EventError
from app.miniapp.state import BOT, CHAT_FILES, QR_DESIGNER
from app.services.chat_files import TTL, ChatFiles
from app.services.event_service import event_qr
from tests import test_miniapp
from tests.test_miniapp import headers

miniapp_client = test_miniapp.client


def data(kind="participants", **changes):
    return {
        "request_id": str(uuid4()),
        "kind": kind,
        "transparent": True,
        "design_id": "",
        **({"member_ids": [200]} if kind == "participants" else {}),
        **changes,
    }


async def finished(client, request):
    job = client.server.app[CHAT_FILES].get(100, client.event_id, request["request_id"])
    await job.task
    return job


@pytest.mark.asyncio
async def test_signed_file_requests_send_selected_workbook_only_to_authenticated_owner(
    miniapp_client,
):
    client = miniapp_client
    await client.events.visit(100, client.event_id)
    await client.events.visit(200, client.event_id)
    path = f"/api/forms/{client.event_id}/files"
    request = data()
    response = await client.post(path + "?chat_id=200", headers=headers(), json=request)
    assert response.status == 202 and response.headers["Cache-Control"] == "no-store"
    result = await response.json()
    assert result["chat_url"] == "https://t.me/example_bot"
    assert (await finished(client, request)).status == "sent"
    bot = client.server.app[BOT]
    bot.send_document.assert_awaited_once()
    sent = bot.send_document.call_args.kwargs
    assert sent["chat_id"] == 100 and sent["parse_mode"] is None
    assert "Owner's event <script>" in sent["caption"]
    assert sent["document"].filename == f"participants-{client.event_id}.xlsx"
    book = load_workbook(BytesIO(sent["document"].data))
    assert book.active.max_row == 2 and book.active["A2"].value == "200"
    metadata = {
        row[0]: row[1] for row in book["Export info"].iter_rows(min_row=2, values_only=True)
    }
    assert metadata["event_id"] == client.event_id
    assert metadata["export_scope"] == "selected" and metadata["participant_count"] == 1
    assert metadata["organizer_telegram_id"] == "100"
    book.close()
    for _ in range(3):
        assert (await client.post(path, headers=headers(), json=request)).status == 202
    assert bot.send_document.await_count == 1
    assert (
        await client.post(path, headers=headers(), json={**request, "member_ids": [100, 200]})
    ).status == 400
    status = await client.get(path + "/" + request["request_id"], headers=headers())
    assert (await status.json())["status"] == "sent"


@pytest.mark.asyncio
async def test_foreign_form_participants_cannot_enter_export_and_empty_selection_never_means_all(
    miniapp_client,
):
    client = miniapp_client
    other = await client.events.create(100, "Other form")
    await client.events.visit(200, other.id)
    request = data()
    path = f"/api/forms/{client.event_id}/files"
    assert (await client.post(path, headers=headers(), json=request)).status == 202
    assert (await finished(client, request)).status == "failed"
    client.server.app[BOT].send_document.assert_not_awaited()
    assert (
        await client.post(path, headers=headers(), json={**data(), "member_ids": []})
    ).status == 400
    missing = data()
    del missing["member_ids"]
    assert (await client.post(path, headers=headers(), json=missing)).status == 400
    assert (
        await client.post(path, headers=headers(), json=data("qr", member_ids=[200]))
    ).status == 400


@pytest.mark.asyncio
@pytest.mark.parametrize("transparent", [True, False])
async def test_qr_file_preserves_preview_bytes_background_and_design_across_restart(
    miniapp_client, transparent
):
    client = miniapp_client
    path = f"/api/events/{client.event_id}"
    expected = await (
        await client.get(path + f"/qr?transparent={str(transparent).lower()}", headers=headers())
    ).read()
    request = data("qr", transparent=transparent)
    assert (await client.post(path + "/files", headers=headers(), json=request)).status == 202
    assert (await finished(client, request)).status == "sent"
    bot = client.server.app[BOT]
    assert bot.send_document.call_args.kwargs["document"].data == expected
    with Image.open(BytesIO(expected)) as image:
        assert ("transparency" in image.info) == transparent
    designer = client.server.app[QR_DESIGNER]
    design_id = str(uuid4())
    images = {
        background: event_qr(
            "https://t.me/example_bot?start=event_" + client.event_id, transparent=background
        )
        for background in (True, False)
    }
    await designer.store.save(100, client.event_id, design_id, images)
    designer.jobs.clear()
    client.server.app[CHAT_FILES].clock = lambda: 100_000_000
    request = data("qr", transparent=transparent, design_id=design_id)
    assert (await client.post(path + "/files", headers=headers(), json=request)).status == 202
    assert (await finished(client, request)).status == "sent"
    assert bot.send_document.call_args.kwargs["document"].data == images[transparent]
    assert bot.send_document.call_args.kwargs["document"].filename.endswith("-design.png")


@pytest.mark.asyncio
async def test_file_endpoints_reject_unsigned_other_owners_and_forged_recipient(miniapp_client):
    client = miniapp_client
    await client.events.visit(200, client.event_id)
    request = data()
    path = f"/api/forms/{client.event_id}/files"
    assert (await client.post(path, json=request)).status == 401
    assert (
        await client.post(path + "?user_id=100", headers=headers(200), json=request)
    ).status == 403
    await client.events.create(200, "Other owner")
    assert (await client.post(path, headers=headers(200), json=request)).status == 400
    assert (
        await client.post(path, headers=headers(), json={**request, "chat_id": 200})
    ).status == 400
    assert (await client.get(path + "/" + request["request_id"])).status == 401
    assert (await client.post(path, headers=headers(), json=request)).status == 202
    await finished(client, request)
    assert (
        await client.get(path + "/" + request["request_id"], headers=headers(200))
    ).status == 400
    assert client.server.app[CHAT_FILES].get(200, client.event_id, request["request_id"]) is None
    assert client.server.app[CHAT_FILES].get(100, str(uuid4()), request["request_id"]) is None
    assert client.server.app[BOT].send_document.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"request_id": "invalid"},
        {"kind": "photo"},
        {"kind": []},
        {"transparent": "false"},
        {"design_id": 12},
        {"design_id": "bad"},
        {"design_id": str(uuid4())},
        {"transparent": False},
        {"member_ids": []},
        {"member_ids": None},
        {"member_ids": [True]},
        {"member_ids": [200, 200]},
        {"member_ids": ["200"]},
        {"member_ids": [0]},
        {"member_ids": list(range(1, 2002))},
    ],
)
async def test_file_validation_never_submits_invalid_requests(miniapp_client, change):
    client = miniapp_client
    response = await client.post(
        f"/api/forms/{client.event_id}/files", headers=headers(), json=data(**change)
    )
    assert response.status == 400
    assert not client.server.app[CHAT_FILES].jobs
    client.server.app[BOT].send_document.assert_not_awaited()


@pytest.mark.asyncio
async def test_minimized_client_does_not_cancel_send_and_close_drains_without_duplicates(
    miniapp_client,
):
    client = miniapp_client
    bot, files = client.server.app[BOT], client.server.app[CHAT_FILES]
    entered, release = asyncio.Event(), asyncio.Event()

    async def sending(**kwargs):
        entered.set()
        await release.wait()
        return SimpleNamespace(message_id=500)

    bot.send_document.side_effect = sending
    request = data("qr")
    path = f"/api/forms/{client.event_id}/files"
    response = await client.post(path, headers=headers(), json=request)
    assert response.status == 202
    response.close()
    await entered.wait()
    assert (await client.post(path, headers=headers(), json=request)).status == 202
    assert (await client.post(path, headers=headers(), json=data("qr"))).status == 400
    assert (
        await client.post(path, headers=headers(), json={**request, "transparent": False})
    ).status == 400
    assert (await client.get("/health")).status == 200
    closing = asyncio.create_task(files.close())
    await asyncio.sleep(0)
    assert not closing.done()
    release.set()
    await closing
    assert bot.send_document.await_count == 1
    assert files.closed and not files.jobs


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (
            TelegramNetworkError(
                method=SendDocument(chat_id=100, document="dummy"), message="private-token"
            ),
            "unknown",
        ),
        (
            TelegramBadRequest(
                method=SendDocument(chat_id=100, document="dummy"), message="private-token"
            ),
            "failed",
        ),
        (
            TelegramRetryAfter(
                method=SendDocument(chat_id=100, document="dummy"),
                message="private-token",
                retry_after=5,
            ),
            "failed",
        ),
    ],
)
async def test_telegram_failure_is_not_retried_or_falsely_reported_sent(
    miniapp_client, failure, expected, caplog
):
    client = miniapp_client
    client.server.app[BOT].send_document.side_effect = failure
    request = data("qr")
    path = f"/api/forms/{client.event_id}/files"
    assert (await client.post(path, headers=headers(), json=request)).status == 202
    job = await finished(client, request)
    assert job.status == expected
    assert (await client.post(path, headers=headers(), json=request)).status == 202
    result = await (await client.get(path + "/" + request["request_id"], headers=headers())).json()
    assert result["status"] == expected and "private" not in str(result) + caplog.text
    assert client.server.app[BOT].send_document.await_count == 1


@pytest.mark.asyncio
async def test_job_cache_and_admission_are_bounded_and_failed_preparation_cannot_send():
    now = [0]
    repository = SimpleNamespace(settings=AsyncMock(side_effect=EventError("private")))
    bot = SimpleNamespace(send_document=AsyncMock(), send_message=AsyncMock())
    files = ChatFiles(repository, bot, None, asyncio.Lock(), clock=lambda: now[0])
    try:
        job = files.submit(100, "event", str(uuid4()), "qr")
        await job.task
        assert job.status == "failed"
        with pytest.raises(EventError, match="few seconds"):
            files.submit(100, "event", str(uuid4()), "qr")
        bot.send_document.assert_not_awaited()
        bot.send_message.assert_awaited_once()
        assert bot.send_message.call_args.kwargs["chat_id"] == 100
        assert "private" not in bot.send_message.call_args.kwargs["text"]
        now[0] += TTL + 1
        job = files.submit(100, "event", str(uuid4()), "qr")
        assert len(files.jobs) == 1
        await job.task
    finally:
        await files.close()


@pytest.mark.asyncio
async def test_delivery_rejects_more_than_eight_active_jobs_and_caches_at_most_256():
    gate = asyncio.Event()
    files = ChatFiles(None, None, None, asyncio.Lock(), clock=lambda: 0)

    async def waiting(job):
        await gate.wait()
        job.status = "sent"

    files._send = waiting
    try:
        for owner in range(8):
            files.submit(owner, "event", str(uuid4()), "qr")
        with pytest.raises(EventError, match="busy"):
            files.submit(9, "event", str(uuid4()), "qr")
        gate.set()
        await asyncio.gather(*(job.task for job in files.jobs.values()))
        for owner in range(8, 256):
            job = files.submit(owner, "event", str(uuid4()), "qr")
            await job.task
        with pytest.raises(EventError, match="busy"):
            files.submit(256, "event", str(uuid4()), "qr")
        assert len(files.jobs) == 256
    finally:
        await files.close()
