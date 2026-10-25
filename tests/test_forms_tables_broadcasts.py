import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from aiogram.exceptions import TelegramForbiddenError, TelegramNetworkError
from aiogram.methods import CopyMessage
from sqlalchemy import func, select

from app.broadcasts import BroadcastRepository
from app.event_errors import EventError
from app.event_repository import EventRepository
from app.events.table import EventTable
from app.models import BroadcastRecipient, EventRegistration, EventTableValues
from app.services.broadcast_worker import BroadcastWorker
from registrar.models import Student
from tests.helpers import complete_student_registration


@pytest_asyncio.fixture
async def workspace(repository):
    for user_id in (100, 200):
        await complete_student_registration(
            repository,
            user_id,
            Student(
                str(user_id),
                "Student",
                f"{user_id}@example.test",
                account=f"{user_id}@example.test",
            ),
        )
    events = EventRepository(repository.db, clock=repository.clock)
    event = await events.create(100, "Advisors recruitment")
    return SimpleNamespace(
        registrations=repository,
        events=events,
        event=event,
        table=EventTable(repository.db, clock=repository.clock),
        broadcasts=BroadcastRepository(repository.db, clock=repository.clock),
    )


def changes(event, **extra):
    return {
        **{
            key: getattr(event, key)
            for key in [
                "title",
                "description",
                "registration_open",
                "response_retention_days",
                "questions",
                "revision",
            ]
        },
        **extra,
    }


@pytest.mark.asyncio
async def test_general_forms_preserve_legacy_creation_and_support_department(workspace):
    w = workspace
    updated = await w.events.configure(
        100, w.event.id, changes(w.event, department="Students' Union")
    )
    assert updated.department == "Students' Union"
    legacy = await w.events.create(100, "Legacy event")
    assert legacy.title == "Legacy event"
    assert (
        await w.events.configure(100, updated.id, changes(updated))
    ).department == updated.department
    with pytest.raises(EventError):
        await w.events.configure(200, w.event.id, changes(updated, department="Another club"))


@pytest.mark.asyncio
async def test_owner_edits_typed_cells_without_mutating_verified_profiles(workspace):
    w = workspace
    question = {
        "id": str(uuid4()),
        "label": "Experience",
        "type": "text",
        "required": True,
        "options": [],
    }
    event = await w.events.configure(100, w.event.id, changes(w.event, questions=[question]))
    await w.events.visit(200, event.id)
    await w.events.submit_form(200, event.id, {question["id"]: "Original"}, event.form_revision)
    before = await w.registrations.verified(200)
    column = {"id": str(uuid4()), "label": "Shortlisted", "type": "checkbox", "options": []}
    columns = await w.table.columns(100, event.id, [column], 1)
    data = {
        "scope": "column",
        "field": column["id"],
        "value": False,
        "revision": 1,
        "columns_revision": columns["columns_revision"],
    }
    first = await w.table.edit(100, event.id, 200, data)
    await w.table.edit(
        100,
        event.id,
        200,
        {
            **data,
            "scope": "answer",
            "field": question["id"],
            "value": "Corrected",
            "revision": first["revision"],
        },
    )
    page = await w.events.answer_page(100, event.id)
    assert page.members[0]["answers"] == {question["id"]: "Corrected"}
    assert page.members[0]["organizer_values"] == {column["id"]: False}
    assert page.members[0]["row_revision"] == 3
    assert (await w.registrations.verified(200)).to_dict() == before.to_dict()
    assert await w.registrations.education_level(200) == "CIFS"
    for actor, field_scope in [(200, "column"), (100, "profile")]:
        with pytest.raises(EventError):
            await w.table.edit(actor, event.id, 200, {**data, "scope": field_scope, "revision": 3})


@pytest.mark.asyncio
async def test_mcq_edits_accept_one_choice_without_silently_replacing_legacy_answers(workspace):
    w = workspace
    question = {
        "id": str(uuid4()),
        "label": "Platform",
        "type": "multiple_choice",
        "required": True,
        "options": ["Java", "Bedrock"],
    }
    event = await w.events.configure(100, w.event.id, changes(w.event, questions=[question]))
    await w.events.submit_form(
        200, event.id, {question["id"]: ["Java", "Bedrock"]}, event.form_revision
    )
    change = {
        "scope": "answer",
        "field": question["id"],
        "value": ["Java", "Bedrock"],
        "revision": 1,
        "columns_revision": 1,
    }
    with pytest.raises(EventError, match="Choose one option"):
        await w.table.edit(100, event.id, 200, change)
    page = await w.events.answer_page(100, event.id)
    assert page.members[0]["answers"] == {question["id"]: ["Java", "Bedrock"]}
    assert page.members[0]["row_revision"] == 1
    updated = await w.table.edit(100, event.id, 200, {**change, "value": ["Bedrock"]})
    assert updated["value"] == ["Bedrock"]
    page = await w.events.answer_page(100, event.id)
    assert page.members[0]["answers"] == {question["id"]: ["Bedrock"]}


@pytest.mark.asyncio
async def test_concurrent_edits_conflict_and_removing_column_redacts_its_values(workspace):
    w = workspace
    await w.events.visit(200, w.event.id)
    column = {"id": str(uuid4()), "label": "Score", "type": "number", "options": []}
    await w.table.columns(100, w.event.id, [column], 1)
    base = {
        "scope": "column",
        "field": column["id"],
        "value": "7",
        "revision": 1,
        "columns_revision": 2,
    }
    results = await asyncio.gather(
        *(w.table.edit(100, w.event.id, 200, {**base, "value": value}) for value in ["7", "8"]),
        return_exceptions=True,
    )
    assert sum(isinstance(r, EventError) for r in results) == 1
    assert sum(isinstance(r, dict) for r in results) == 1
    await w.table.columns(100, w.event.id, [], 2)
    assert (await w.events.answer_page(100, w.event.id)).members[0]["organizer_values"] == {}
    with pytest.raises(EventError, match="Columns changed"):
        await w.table.edit(100, w.event.id, 200, {**base, "revision": 2})


@pytest.mark.asyncio
async def test_editable_values_expire_without_removing_enrollment(workspace):
    w = workspace
    await w.events.visit(200, w.event.id)
    column = {"id": str(uuid4()), "label": "Notes", "type": "text", "options": []}
    await w.table.columns(100, w.event.id, [column], 1)
    base = {
        "scope": "column",
        "field": column["id"],
        "value": "Temporary note",
        "revision": 1,
        "columns_revision": 2,
    }
    await w.table.edit(100, w.event.id, 200, base)
    w.registrations.test_clock[0] += timedelta(days=31)
    assert (await w.events.answer_page(100, w.event.id)).members[0]["organizer_values"] == {}
    with pytest.raises(EventError, match="expired"):
        await w.table.edit(100, w.event.id, 200, {**base, "revision": 2})
    await w.events.purge_answers()
    async with w.registrations.db.transaction() as session:
        assert await session.scalar(select(func.count()).select_from(EventTableValues)) == 0
        assert await session.scalar(select(func.count()).select_from(EventRegistration)) == 1
    assert await w.registrations.verified(200) is not None


async def preview(workspace, recipients=None):
    w = workspace
    await w.events.visit(200, w.event.id)
    draft = await w.broadcasts.create(100, w.event.id, recipients or [200], str(uuid4()))
    await w.broadcasts.compose(100, draft["id"], 500)
    return await w.broadcasts.preview(
        100, draft["id"], 500, 600, "rich_message", original_message_id=400
    )


@pytest.mark.asyncio
async def test_finished_history_filters_before_pagination_and_reports_pending_delivery(workspace):
    w = workspace
    finished = set()
    for _ in range(11):
        ready = await preview(w)
        await w.broadcasts.queue(100, ready["id"], ready["revision"])
        await w.broadcasts.finish(await w.broadcasts.claim(), "sent", message_id=700)
        finished.add(ready["id"])
        w.registrations.test_clock[0] += timedelta(minutes=7)
    draft = await w.broadcasts.create(100, w.event.id, [200], str(uuid4()))
    await w.broadcasts.cancel(100, draft["id"])
    await w.broadcasts.create(100, w.event.id, [200], str(uuid4()))
    await preview(w)
    ready = await preview(w)
    await w.broadcasts.queue(100, ready["id"], ready["revision"])

    pages = [await w.broadcasts.page(100, w.event.id, n, completed_only=True) for n in (0, 1)]
    assert [len(page["broadcasts"]) for page in pages] == [10, 1]
    assert all(page["total"] == 11 and page["pages"] == 2 and page["has_active"] for page in pages)
    assert {item["id"] for page in pages for item in page["broadcasts"]} == finished
    assert all(item["status"] == "completed" for page in pages for item in page["broadcasts"])
    with pytest.raises(EventError):
        await w.broadcasts.page(200, w.event.id, completed_only=True)


@pytest.mark.asyncio
async def test_audience_is_owner_scoped_and_creation_and_confirmation_are_idempotent(workspace):
    w = workspace
    await w.events.visit(200, w.event.id)
    request_id = str(uuid4())
    first = await w.broadcasts.create(100, w.event.id, [200], request_id)
    assert (await w.broadcasts.create(100, w.event.id, [200], request_id))["id"] == first["id"]
    assert await w.broadcasts.claim() is None
    with pytest.raises(EventError):
        await w.broadcasts.create(100, w.event.id, [100], str(uuid4()))
    with pytest.raises(EventError):
        await w.broadcasts.get(200, first["id"])
    with pytest.raises(EventError):
        await w.broadcasts.queue(100, first["id"], first["revision"])
    await w.broadcasts.compose(100, first["id"], 500)
    assert await w.broadcasts.reply_draft(200, 500) is None
    ready = await w.broadcasts.preview(100, first["id"], 500, 600, "text")
    await asyncio.gather(
        *(w.broadcasts.queue(100, first["id"], ready["revision"]) for _ in range(2))
    )
    claim = await w.broadcasts.claim()
    assert claim["telegram_id"] == 200 and claim["source_message_id"] == 600
    assert await w.broadcasts.claim() is None
    await w.broadcasts.finish(claim, "sent", message_id=700)
    done = await w.broadcasts.get(100, first["id"])
    assert done["counts"] == {"sent": 1} and done["status"] == "completed"


@pytest.mark.asyncio
async def test_old_preview_and_unrelated_replies_cannot_confirm_a_new_message(workspace):
    w = workspace
    ready = await preview(w)
    await w.broadcasts.compose(100, ready["id"], 501)
    assert await w.broadcasts.reply_draft(100, 500) is None
    with pytest.raises(EventError):
        await w.broadcasts.queue(100, ready["id"], ready["revision"])
    with pytest.raises(EventError):
        await w.broadcasts.preview(100, ready["id"], 500, 602, "text")
    await w.broadcasts.cancel(100, ready["id"])
    assert await w.broadcasts.reply_draft(100, 501) is None
    assert await w.broadcasts.claim() is None


@pytest.mark.asyncio
async def test_restart_does_not_duplicate_an_ambiguously_submitted_message(workspace):
    w = workspace
    draft = await preview(w)
    await w.broadcasts.queue(100, draft["id"], draft["revision"])
    assert await w.broadcasts.claim() is not None
    await w.broadcasts.recover()
    await w.broadcasts.maintenance()
    assert await w.broadcasts.claim() is None
    state = await w.broadcasts.get(100, draft["id"])
    assert state["status"] == "completed" and state["counts"] == {"unknown": 1}


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["sent", "blocked", "unknown"])
async def test_worker_copies_the_exact_preview_and_records_safe_outcomes(workspace, outcome):
    w = workspace
    draft = await preview(w)
    await w.broadcasts.queue(100, draft["id"], draft["revision"])
    claim = await w.broadcasts.claim()
    bot = SimpleNamespace(copy_message=AsyncMock(return_value=SimpleNamespace(message_id=700)))
    method = CopyMessage(chat_id=200, from_chat_id=100, message_id=600)
    if outcome == "blocked":
        bot.copy_message.side_effect = TelegramForbiddenError(
            method=method, message="private details"
        )
    if outcome == "unknown":
        bot.copy_message.side_effect = TelegramNetworkError(method=method, message="private-token")
    await BroadcastWorker(w.broadcasts, bot).deliver(claim)
    assert bot.copy_message.await_count == 1
    assert bot.copy_message.await_args.kwargs["allow_paid_broadcast"] is False
    assert bot.copy_message.await_args.kwargs["message_id"] == 600
    expected = {"sent": "sent", "blocked": "failed", "unknown": "unknown"}[outcome]
    assert (await w.broadcasts.get(100, draft["id"]))["counts"] == {expected: 1}
    async with w.registrations.db.transaction() as session:
        row = await session.get(BroadcastRecipient, (draft["id"], 200))
        assert "private" not in (row.error_code or "")


@pytest.mark.asyncio
async def test_broadcast_audience_expires_but_statistics_remain(workspace):
    w = workspace
    draft = await preview(w)
    await w.broadcasts.queue(100, draft["id"], draft["revision"])
    await w.broadcasts.finish(await w.broadcasts.claim(), "sent", message_id=700)
    w.registrations.test_clock[0] += timedelta(days=31)
    await w.broadcasts.maintenance()
    state = await w.broadcasts.get(100, draft["id"])
    assert state["counts"] == {"sent": 1} and state["total"] == 1
    assert state["source_message_id"] is None
    assert state["original_message_id"] is None
    async with w.registrations.db.transaction() as session:
        assert await session.scalar(select(func.count()).select_from(BroadcastRecipient)) == 0


@pytest.mark.asyncio
async def test_retention_extension_cannot_reopen_expired_editing_after_cleanup(workspace):
    w = workspace
    await w.events.visit(200, w.event.id)
    column = {"id": str(uuid4()), "label": "Note", "type": "text", "options": []}
    await w.table.columns(100, w.event.id, [column], 1)
    original = {
        "scope": "column",
        "field": column["id"],
        "value": "Temporary",
        "revision": 1,
        "columns_revision": 2,
    }
    await w.table.edit(100, w.event.id, 200, original)
    shorter = await w.events.configure(100, w.event.id, changes(w.event, response_retention_days=1))
    w.registrations.test_clock[0] += timedelta(days=2)
    await w.events.purge_answers()
    await w.events.configure(100, w.event.id, changes(shorter, response_retention_days=90))
    with pytest.raises(EventError, match="expired"):
        await w.table.edit(100, w.event.id, 200, {**original, "revision": 2})


@pytest.mark.asyncio
async def test_flood_wait_has_a_retry_budget_and_cancel_preserves_inflight_outcome(workspace):
    w = workspace
    draft = await preview(w)
    await w.broadcasts.queue(100, draft["id"], draft["revision"])
    for attempt in range(5):
        claim = await w.broadcasts.claim()
        assert claim["attempts"] == attempt + 1
        await w.broadcasts.finish(claim, "pending", retry_after=2, error_code="rate_limited")
        assert await w.broadcasts.claim() is None
        w.registrations.test_clock[0] += timedelta(seconds=2)
    result = await w.broadcasts.get(100, draft["id"])
    assert result["counts"] == {"failed": 1} and result["status"] == "completed"
    w.registrations.test_clock[0] += timedelta(seconds=60)
    next_draft = await w.broadcasts.create(100, w.event.id, [200], str(uuid4()))
    await w.broadcasts.compose(100, next_draft["id"], 502)
    ready = await w.broadcasts.preview(100, next_draft["id"], 502, 602, "text")
    await w.broadcasts.queue(100, ready["id"], ready["revision"])
    claim = await w.broadcasts.claim()
    await w.broadcasts.cancel(100, ready["id"])
    await w.broadcasts.finish(claim, "sent", message_id=700)
    assert (await w.broadcasts.get(100, ready["id"]))["counts"] == {"sent": 1}
    assert (await w.broadcasts.get(100, ready["id"]))["status"] == "cancelled"


@pytest.mark.asyncio
async def test_new_schema_upgrades_existing_profiles_responses_and_retention(workspace):
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    w = workspace
    question = {
        "id": str(uuid4()),
        "label": "Experience",
        "type": "text",
        "required": True,
        "options": [],
    }
    event = await w.events.configure(100, w.event.id, changes(w.event, questions=[question]))
    await w.events.submit_form(
        200, event.id, {question["id"]: "Preserved response"}, event.form_revision
    )
    event = await w.events.configure(100, event.id, changes(event, response_retention_days=7))
    event = await w.events.configure(100, event.id, changes(event, response_retention_days=90))
    person = await w.registrations.verified(200)
    async with w.registrations.db.engine.begin() as connection:

        def legacy_then_upgrade(sync):
            cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
            cfg.attributes["connection"] = sync
            command.downgrade(cfg, "0006_event_qr_designs")
            command.upgrade(cfg, "head")

        await connection.run_sync(legacy_then_upgrade)
    assert (await w.registrations.verified(200)).to_dict() == person.to_dict()
    page = await w.events.answer_page(100, event.id)
    assert page.members[0]["answers"] == {question["id"]: "Preserved response"}
    assert page.event.table_columns == []
    assert (
        page.members[0]["editable_until"]
        == (w.registrations.clock() + timedelta(days=7)).isoformat()
    )
