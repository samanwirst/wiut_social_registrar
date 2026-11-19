from datetime import timedelta
from io import BytesIO
from uuid import uuid4

import pytest
from aiogram.methods import (
    SendAnimation,
    SendAudio,
    SendDocument,
    SendPhoto,
    SendVideo,
    SendVideoNote,
    SendVoice,
)
from aiogram.types import Chat, Message
from openpyxl import load_workbook

from app.event_forms import validate_answers, validate_questions
from app.event_repository import EventError
from app.events.table import EventTable
from app.media_answers import MEDIA_LABELS, attachment_from_message
from app.services.participant_export import participants_xlsx
from app.surveys import EventSurvey
from tests import test_bot, test_miniapp
from tests.test_bot import form_event, methods, send
from tests.test_event_forms import configured, question, registered

bot_app = test_bot.app
api_client = test_miniapp.client


def attachment(kind="document", **changes):
    return {
        "kind": kind,
        "file_id": "synthetic-file-id",
        "file_unique_id": "synthetic-unique-id",
        **changes,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", [*MEDIA_LABELS, "media"])
async def test_media_progress_is_durable_and_final_answer_is_atomic_and_owner_scoped(
    repository, kind
):
    questions = [question(kind), question()]
    events, event = await configured(repository, questions)
    await registered(repository, 200)
    survey = EventSurvey(events)
    await events.visit(200, event.id)
    await survey.begin(200, event.id)
    value = attachment("voice" if kind == "media" else kind)
    step, completed = await survey.respond(200, attachment=value)
    assert completed is None and step.index == 1
    assert (await events.members(100, event.id)).total == 0
    resumed = await EventSurvey(events).resume(200)
    assert resumed.answers[questions[0]["id"]] == value
    _, completed = await survey.respond(200, text="Done")
    assert completed.id == event.id
    page = await events.answer_page(100, event.id)
    visible = page.members[0]["answers"][questions[0]["id"]]
    assert "file_id" not in visible and "file_unique_id" not in visible
    assert len(visible["payload"]) <= 64
    stored = await events.attachment(100, visible["payload"])
    assert stored[-1] == value
    await repository.cancel_current(200)
    assert (await events.attachment(100, visible["payload"]))[-1] == value
    with pytest.raises(EventError):
        await events.attachment(200, visible["payload"])
    for payload in (
        "file_invalid",
        visible["payload"].replace(questions[0]["id"].replace("-", ""), uuid4().hex),
    ):
        with pytest.raises(EventError):
            await events.attachment(100, payload)
    repository.test_clock[0] += timedelta(days=31)
    with pytest.raises(EventError, match="no longer available"):
        await events.attachment(100, visible["payload"])
    assert (await events.answer_page(100, event.id)).members[0]["answers"] is None
    assert (await events.members(100, event.id)).total == 1


@pytest.mark.asyncio
async def test_wrong_media_type_does_not_advance_and_optional_attachment_can_be_skipped(repository):
    questions = [question("photo"), question("voice", required=False)]
    events, event = await configured(repository, questions)
    survey = EventSurvey(events)
    await events.visit(100, event.id)
    initial = await survey.begin(100, event.id)
    for value in (None, attachment("document")):
        with pytest.raises(EventError, match="photo"):
            await survey.respond(100, text="Not a photo", attachment=value)
        assert (await survey.resume(100)).token == initial.token
    step, _ = await survey.respond(100, attachment=attachment("photo"))
    _, completed = await survey.respond(100, token=step.token, action="skip")
    assert completed.id == event.id
    page = await events.answer_page(100, event.id)
    assert questions[1]["id"] not in page.members[0]["answers"]


@pytest.mark.asyncio
async def test_http_and_table_mutations_cannot_forge_telegram_attachment_references(repository):
    questions = [question("document")]
    events, event = await configured(repository, questions)
    await events.visit(100, event.id)
    value = attachment(file_name="CV.pdf", caption="A literal =formula")
    with pytest.raises(EventError, match="bot chat"):
        await events.submit_form(100, event.id, {questions[0]["id"]: value}, event.form_revision)
    survey = EventSurvey(events)
    await survey.begin(100, event.id)
    await survey.respond(100, attachment=value)
    page = await events.answer_page(100, event.id)
    table = EventTable(repository.db, clock=repository.clock)
    with pytest.raises(EventError):
        await table.edit(
            100,
            event.id,
            100,
            {
                "scope": "answer",
                "field": questions[0]["id"],
                "value": value,
                "revision": page.members[0]["row_revision"],
                "columns_revision": event.columns_revision,
            },
        )
    exported = await events.export_members(100, event.id)
    book = load_workbook(BytesIO(participants_xlsx(exported)))
    assert book["Participants"].cell(2, 7).value == "CV.pdf\nA literal =formula"
    assert all(
        "synthetic-file-id" not in str(cell.value)
        for sheet in book
        for row in sheet
        for cell in row
    )


def test_media_definition_and_untrusted_metadata_validation():
    q = question("document")
    assert validate_questions([q]) == [q]
    for value in (
        "file-id",
        attachment(file_id=""),
        attachment(file_size=-1),
        attachment(file_size=True),
        attachment(url="https://example.test"),
        attachment(caption="x" * 1025),
    ):
        with pytest.raises(EventError):
            validate_answers([q], {q["id"]: value})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,method",
    [
        ("photo", SendPhoto),
        ("document", SendDocument),
        ("voice", SendVoice),
        ("video", SendVideo),
        ("audio", SendAudio),
        ("animation", SendAnimation),
        ("video_note", SendVideoNote),
    ],
)
async def test_telegram_upload_and_owner_download_preserve_attachment_type(bot_app, kind, method):
    app = bot_app
    event = await form_event(app, [("Upload your work", "media", True), ("Comment", "text", True)])
    await send(app, f"/start event_{event.id}")
    fields = {"file_id": "synthetic-file-id", "file_unique_id": "synthetic-unique-id"}
    if kind in {"photo", "video", "animation"}:
        fields.update(width=640, height=360)
    if kind in {"voice", "video", "audio", "animation", "video_note"}:
        fields["duration"] = 3
    if kind == "video_note":
        fields["length"] = 240
    if kind == "document":
        fields["file_name"] = "CV.pdf"
    media = [fields] if kind == "photo" else fields
    replies = await send(app, **{kind: media})
    assert "Comment" in replies[-1].text
    await send(app, "Done")
    page = await app.event_repository.answer_page(100, event.id)
    visible = page.members[0]["answers"][event.questions[0]["id"]]
    assert visible["kind"] == kind
    await send(app, "/start " + visible["payload"])
    assert getattr(methods(app, method)[-1], kind) == fields["file_id"]
    before = len(methods(app, method))
    await send(app, "/start " + visible["payload"], user_id=200)
    assert len(methods(app, method)) == before


def test_photo_size_selection_and_albums():
    sizes = [
        dict(file_id="small", file_unique_id="s", width=100, height=100),
        dict(file_id="large", file_unique_id="l", width=640, height=360),
    ]
    message = Message(message_id=1, date=0, chat=Chat(id=100, type="private"), photo=sizes)
    assert attachment_from_message(message)["file_id"] == "large"
    with pytest.raises(EventError, match="without an album"):
        attachment_from_message(message.model_copy(update={"media_group_id": "album"}))


@pytest.mark.asyncio
async def test_album_does_not_complete_or_advance_a_form(bot_app):
    app = bot_app
    event = await form_event(app, [("Your photo", "photo", True)])
    await send(app, f"/start event_{event.id}")
    initial = await app.event_survey.resume(100)
    replies = await send(
        app,
        media_group_id="album",
        photo=[dict(file_id="photo", file_unique_id="p", width=640, height=360)],
    )
    assert "without an album" in replies[-1].text
    assert (await app.event_survey.resume(100)).token == initial.token
    assert (await app.event_repository.members(100, event.id)).total == 0


@pytest.mark.asyncio
async def test_signed_owner_api_exposes_only_attachment_presentation_and_rejects_forgery(
    api_client,
):
    from tests.test_event_forms import configuration
    from tests.test_miniapp import headers

    client = api_client
    events = client.events
    event = await events.settings(100, client.event_id)
    event = await events.configure(
        100, event.id, configuration(event, questions=[question("document")])
    )
    survey = EventSurvey(events)
    await events.visit(200, event.id)
    await survey.begin(200, event.id)
    await survey.respond(200, attachment=attachment(file_name="CV.pdf"))
    response = await client.get(f"/api/forms/{event.id}/members", headers=headers())
    assert response.status == 200
    body = await response.json()
    media = body["members"][0]["answers"][event.questions[0]["id"]]
    assert media["file_name"] == "CV.pdf" and media["url"].startswith(
        "https://t.me/example_bot?start=file_"
    )
    assert "file_id" not in media and "file_unique_id" not in media
    assert "synthetic-file-id" not in str(body)
    assert (await client.get(f"/api/forms/{event.id}/members", headers=headers(200))).status == 403
    assert (await client.get(f"/api/forms/{event.id}/members")).status == 401
    response = await client.patch(
        f"/api/forms/{event.id}/members/200",
        headers=headers(),
        json={
            "scope": "answer",
            "field": event.questions[0]["id"],
            "value": attachment(),
            "revision": body["members"][0]["row_revision"],
            "columns_revision": body["columns_revision"],
        },
    )
    assert response.status == 400
