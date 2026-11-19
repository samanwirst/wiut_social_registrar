import asyncio
import json
from datetime import timedelta
from io import BytesIO
from uuid import UUID, uuid4

import pytest
from openpyxl import load_workbook
from sqlalchemy import select

from app.broadcasts import BroadcastRepository
from app.event_repository import EventError
from app.events.table import EventTable
from app.media_answers import attachment_reference
from app.models import EventRegistration
from app.services.participant_export import participants_xlsx
from app.surveys import EventSurvey
from tests import test_bot, test_miniapp
from tests.test_bot import send
from tests.test_event_forms import configuration, configured, question, registered
from tests.test_media_answers import attachment

bot_app = test_bot.app
api_client = test_miniapp.client


async def anonymous_form(repository, questions=None):
    events, event = await configured(repository, questions)
    event = await events.configure(100, event.id, configuration(event, anonymous=True))
    return events, event


def assert_private(page):
    for member in page.members:
        assert set(member) <= {
            "response_id",
            "row_revision",
            "answers",
            "organizer_values",
            "can_edit",
        }
        UUID(member["response_id"])
    assert all(isinstance(value, str) and str(UUID(value)) == value for value in page.member_ids)
    body = json.dumps(page.members)
    for forbidden in (
        "telegram_id",
        "student_id",
        "email",
        "phone_number",
        "education_level",
        "registered_at",
        "registration_id",
        "editable_until",
        "Student 200",
        "200@example.test",
    ):
        assert forbidden not in body


@pytest.mark.asyncio
async def test_anonymous_responses_keep_internal_dedup_but_expose_no_profile_or_timing(repository):
    events, event = await anonymous_form(repository)
    await registered(repository, 200)
    values = {event.questions[0]["id"]: "Useful feedback"}
    assert (await events.submit_form(200, event.id, values, event.form_revision))[1]
    assert not (await events.submit_form(200, event.id, values, event.form_revision))[1]
    assert (await events.visit(200, event.id))[1] == "already_registered"
    page = await events.answer_page(100, event.id)
    assert_private(page)
    assert page.total == 1 and page.members[0]["answers"] == values
    assert page.members[0]["response_id"] in page.member_ids
    async with repository.db.transaction() as session:
        stored = await session.scalar(
            select(EventRegistration).where(EventRegistration.event_id == event.id)
        )
        assert stored.telegram_user_id == 200 and stored.outlook_profile_id is not None
        assert stored.anonymous_id == page.members[0]["response_id"]
    assert set((await events.members(100, event.id)).members[0]) == {"response_id"}
    with pytest.raises(EventError):
        await events.answer_page(200, event.id)
    repository.test_clock[0] += timedelta(days=31)
    expired = await events.answer_page(100, event.id)
    assert_private(expired)
    assert expired.members[0]["answers"] is None and expired.members[0]["can_edit"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("anonymous", [False, True])
@pytest.mark.parametrize("with_questions", [False, True])
async def test_anonymity_locks_after_any_first_registration(repository, anonymous, with_questions):
    events, event = await configured(repository)
    assert not event.anonymous and not event.anonymous_locked
    event = await events.configure(
        100,
        event.id,
        configuration(
            event, anonymous=anonymous, questions=event.questions if with_questions else []
        ),
    )
    if with_questions:
        await events.submit_form(
            100, event.id, {event.questions[0]["id"]: "Done"}, event.form_revision
        )
    else:
        await events.visit(100, event.id)
    current = await events.settings(100, event.id)
    assert current.anonymous_locked
    await events.purge_answers(100, event.id)
    with pytest.raises(EventError, match="first registration"):
        await events.configure(100, event.id, configuration(current, anonymous=not anonymous))
    updated = await events.configure(
        100, event.id, configuration(current, anonymous=anonymous, title="New title")
    )
    assert updated.anonymous == anonymous


@pytest.mark.asyncio
async def test_older_settings_payload_cannot_disable_anonymity(repository):
    events, event = await anonymous_form(repository)
    event = await events.configure(
        100, event.id, configuration(event, description="Updated by an older client")
    )
    assert event.anonymous
    for bad in ("true", 1, None):
        with pytest.raises(EventError):
            await events.configure(100, event.id, configuration(event, anonymous=bad))


@pytest.mark.asyncio
async def test_anonymity_change_invalidates_drafts_before_first_submission(repository):
    events, event = await configured(repository, [question(), question()])
    survey = EventSurvey(events)
    await events.visit(100, event.id)
    await survey.begin(100, event.id)
    old, _ = await survey.respond(100, text="Old disclosure")
    event = await events.configure(100, event.id, configuration(event, anonymous=True))
    with pytest.raises(EventError, match="updated"):
        await survey.respond(100, text="Stale final answer")
    fresh = await survey.resume(100)
    assert fresh.index == 0 and fresh.answers == {} and fresh.token != old.token
    assert fresh.event.anonymous


@pytest.mark.asyncio
async def test_anonymous_selection_and_cell_edits_use_form_local_opaque_ids(repository):
    events, event = await anonymous_form(repository)
    await registered(repository, 200)
    for user_id in (100, 200):
        await events.submit_form(
            user_id, event.id, {event.questions[0]["id"]: "Original"}, event.form_revision
        )
    page = await events.answer_page(100, event.id)
    assert_private(page)
    row = page.members[0]
    payload = {
        "scope": "answer",
        "field": event.questions[0]["id"],
        "value": "Edited",
        "revision": row["row_revision"],
        "columns_revision": event.columns_revision,
    }
    table = EventTable(repository.db, clock=repository.clock)
    for raw in (100, 200, str(uuid4())):
        with pytest.raises(EventError):
            await table.edit(100, event.id, raw, payload)
    change = await table.edit(100, event.id, row["response_id"], payload)
    assert change["value"] == "Edited"
    selected = await events.export_members(100, event.id, member_ids=[row["response_id"]])
    assert (
        selected.total == 1 and selected.members[0]["answers"][event.questions[0]["id"]] == "Edited"
    )
    for wrong in ([100], [str(uuid4())], [100, row["response_id"]]):
        with pytest.raises(EventError):
            await events.export_members(100, event.id, member_ids=wrong)
    broadcasts = BroadcastRepository(repository.db, clock=repository.clock)
    with pytest.raises(EventError, match="anonymous"):
        await broadcasts.create(100, event.id, [200], str(uuid4()))
    with pytest.raises(EventError, match="anonymous"):
        await broadcasts.page(100, event.id)


@pytest.mark.asyncio
async def test_anonymous_workbook_contains_only_answers_and_nonidentifying_metadata(repository):
    questions = [question("text"), question("multiple_choice")]
    events, event = await anonymous_form(repository, questions)
    await registered(repository, 200)
    await events.submit_form(
        200,
        event.id,
        {questions[0]["id"]: "Safe feedback", questions[1]["id"]: ["Option A"]},
        event.form_revision,
    )
    page = await events.export_members(100, event.id)
    assert_private(page)
    book = load_workbook(BytesIO(participants_xlsx(page)))
    sheet = book["Participants"]
    assert sheet.cell(1, 1).value == "Response" and sheet.cell(2, 1).value == 1
    assert sheet.cell(2, 2).value == "Safe feedback"
    raw = "\n".join(str(cell.value) for worksheet in book for row in worksheet for cell in row)
    for forbidden in (
        "telegram_id",
        "student_id",
        "registration_id",
        "registered_at",
        "Email",
        "Phone",
        "Level",
        "Student 200",
        "200@example.test",
        page.members[0]["response_id"],
    ):
        assert forbidden not in raw
    assert "wiut-social-registrar.anonymous-responses" in raw


@pytest.mark.asyncio
async def test_anonymous_media_links_have_no_registration_identity_and_reject_legacy_links(
    repository,
):
    events, event = await anonymous_form(repository, [question("document")])
    await registered(repository, 200)
    survey = EventSurvey(events)
    await events.visit(200, event.id)
    await survey.begin(200, event.id)
    await survey.respond(200, attachment=attachment(file_name="Work.pdf"))
    page = await events.answer_page(100, event.id)
    assert_private(page)
    answer = page.members[0]["answers"][event.questions[0]["id"]]
    assert len(answer["payload"]) <= 64
    identity, _ = attachment_reference(answer["payload"])
    assert identity == page.members[0]["response_id"]
    result = await events.attachment(100, answer["payload"])
    assert result[2] is None
    with pytest.raises(EventError):
        await events.attachment(200, answer["payload"])
    async with repository.db.transaction() as session:
        raw_id = await session.scalar(
            select(EventRegistration.id).where(EventRegistration.event_id == event.id)
        )
    with pytest.raises(EventError):
        await events.attachment(100, f"file_{raw_id}_{event.questions[0]['id'].replace('-', '')}")


@pytest.mark.asyncio
async def test_mode_change_and_submission_cannot_commit_an_identified_anonymous_response(
    repository,
):
    events, event = await configured(repository)
    await registered(repository, 200)
    results = await asyncio.gather(
        events.configure(100, event.id, configuration(event, anonymous=True)),
        events.submit_form(
            200, event.id, {event.questions[0]["id"]: "Answer"}, event.form_revision
        ),
        return_exceptions=True,
    )
    assert any(isinstance(result, EventError) for result in results)
    current = await events.settings(100, event.id)
    if current.anonymous:
        await events.submit_form(
            200, event.id, {event.questions[0]["id"]: "Answer"}, current.form_revision
        )
        assert_private(await events.answer_page(100, event.id))
    else:
        assert current.anonymous_locked


@pytest.mark.asyncio
async def test_anonymous_api_and_chat_export_never_expose_profile_or_hidden_identifiers(api_client):
    from app.miniapp.state import BOT, CHAT_FILES
    from tests.test_miniapp import headers

    client = api_client
    events = client.events
    event = await events.settings(100, client.event_id)
    event = await events.configure(
        100, event.id, configuration(event, anonymous=True, questions=[question(label="Feedback")])
    )
    await events.submit_form(
        200, event.id, {event.questions[0]["id"]: "A useful answer"}, event.form_revision
    )
    path = f"/api/forms/{event.id}"
    result = await client.get(path + "/members", headers=headers())
    assert result.status == 200
    data = await result.json()
    assert data["anonymous"]
    row = data["members"][0]
    assert set(row) == {"response_id", "row_revision", "answers", "organizer_values", "can_edit"}
    assert data["member_ids"] == [row["response_id"]]
    assert (await client.get(path + "/members")).status == 401
    assert (await client.get(path + "/members", headers=headers(200))).status == 403
    edit = {
        "scope": "answer",
        "field": event.questions[0]["id"],
        "value": "An edited answer",
        "revision": row["row_revision"],
        "columns_revision": data["columns_revision"],
    }
    assert (await client.patch(path + "/members/200", headers=headers(), json=edit)).status == 400
    assert (
        await client.patch(path + "/members/" + row["response_id"], headers=headers(), json=edit)
    ).status == 200
    assert (
        await client.post(
            path + "/broadcasts",
            headers=headers(),
            json={"recipient_ids": [200], "request_id": str(uuid4())},
        )
    ).status == 400
    assert (await client.get(path + "/broadcasts", headers=headers())).status == 400
    settings = await (await client.get(path, headers=headers())).json()
    assert settings["anonymous_locked"]
    assert (
        await client.put(path, headers=headers(), json=configuration(event, anonymous=False))
    ).status == 400
    request_id = str(uuid4())
    delivery = await client.post(
        path + "/files",
        headers=headers(),
        json={
            "request_id": request_id,
            "kind": "participants",
            "transparent": True,
            "design_id": "",
            "member_ids": [row["response_id"]],
        },
    )
    assert delivery.status == 202
    await client.server.app[CHAT_FILES].get(100, event.id, request_id).task
    sent = client.server.app[BOT].send_document.await_args.kwargs["document"]
    book = load_workbook(BytesIO(sent.data))
    raw = str([[cell.value for row in sheet for cell in row] for sheet in book])
    assert "An edited answer" in raw
    for forbidden in (
        "telegram_id",
        "student_id",
        "registration_id",
        "200@example.test",
        row["response_id"],
    ):
        assert forbidden not in raw


@pytest.mark.asyncio
async def test_projection_does_not_race_anonymity_change_and_first_response(
    repository, monkeypatch
):
    import app.events.queries as queries

    events, event = await configured(repository)
    await registered(repository, 200)
    entered, release = asyncio.Event(), asyncio.Event()
    original = queries.owned_event

    async def hold(*args, **kwargs):
        value = await original(*args, **kwargs)
        entered.set()
        await release.wait()
        return value

    monkeypatch.setattr(queries, "owned_event", hold)
    reader = asyncio.create_task(events.answer_page(100, event.id))
    await entered.wait()

    async def change_and_submit():
        updated = await events.configure(100, event.id, configuration(event, anonymous=True))
        await events.submit_form(
            200, event.id, {event.questions[0]["id"]: "Private feedback"}, updated.form_revision
        )

    writer = asyncio.create_task(change_and_submit())
    try:
        await asyncio.sleep(0.05)
        assert not writer.done()
    finally:
        release.set()
    assert (await reader).members == []
    await writer
    monkeypatch.setattr(queries, "owned_event", original)
    assert_private(await events.answer_page(100, event.id))


@pytest.mark.asyncio
async def test_migration_keeps_identified_records_and_locks_existing_forms(repository):
    from alembic import command
    from alembic.config import Config

    events, event = await configured(repository)
    await events.submit_form(
        100, event.id, {event.questions[0]["id"]: "Existing answer"}, event.form_revision
    )
    original = (await events.answer_page(100, event.id)).members

    def downgrade(connection):
        config = Config("alembic.ini")
        config.attributes["connection"] = connection
        command.downgrade(config, "0008_broadcast_original_message")

    async with repository.db.engine.begin() as connection:
        await connection.run_sync(downgrade)
    await repository.db.migrate()
    restored = await events.settings(100, event.id)
    assert not restored.anonymous and restored.anonymous_locked
    assert (await events.answer_page(100, event.id)).members == original


@pytest.mark.asyncio
async def test_anonymous_media_delivery_has_no_student_identifier_in_chat(bot_app):
    from aiogram.methods import SendDocument, SendMessage

    app = bot_app
    event = await test_bot.form_event(app, [("Your file", "document", True)])
    event = await app.event_repository.configure(
        100, event.id, configuration(event, anonymous=True)
    )
    await send(app, f"/start event_{event.id}")
    await send(
        app,
        document={
            "file_id": "synthetic-file-id",
            "file_unique_id": "synthetic-unique-id",
            "file_name": "Work.pdf",
        },
    )
    value = (await app.event_repository.answer_page(100, event.id)).members[0]["answers"][
        event.questions[0]["id"]
    ]
    before = len(app.bot.session.call_args_list)
    await send(app, "/start " + value["payload"])
    outgoing = [call.args[1] for call in app.bot.session.call_args_list[before:]]
    assert any(isinstance(message, SendDocument) for message in outgoing)
    text = "\n".join(message.text for message in outgoing if isinstance(message, SendMessage))
    assert "Anonymous response" in text
    assert "00000001" not in text and "student@example.test" not in text
