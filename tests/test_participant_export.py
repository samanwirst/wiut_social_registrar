import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4
from zipfile import ZipFile

import pytest
from aiogram.types import User
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from app.events.table import EventTable
from app.miniapp import export_routes
from app.miniapp.state import EXPORT_LOCK, REPOSITORY, USER
from app.services import participant_export
from app.services.participant_export import XLSX_CONTENT_TYPE, participants_xlsx
from app.services.participant_export_schema import FORMAT, SCHEMA_VERSION
from registrar.models import Student
from tests import test_miniapp
from tests.helpers import complete_student_registration
from tests.test_event_forms import configuration, question
from tests.test_miniapp import headers

miniapp_client = test_miniapp.client


def workbook(content):
    return load_workbook(BytesIO(content))


def export_page(questions, columns, members):
    return SimpleNamespace(
        event=SimpleNamespace(
            id="633ccf54-0d4a-41bb-beb8-b9a6aec96664",
            title="Campus event",
            department="Student Union",
            creator_telegram_user_id=2**63 - 1,
            created_at=datetime(2026, 10, 27, tzinfo=timezone.utc),
            revision=3,
            form_revision=2,
            columns_revision=4,
            questions=questions,
            table_columns=columns,
        ),
        members=members,
        export_scope="selected",
    )


def manifest(book):
    return {row[0]: row[1] for row in book["Export info"].iter_rows(min_row=2, values_only=True)}


def column_map(book):
    sheet = book["Columns"]
    names = [cell.value for cell in sheet[1]]
    return {
        row[2]: dict(zip(names, row, strict=True))
        for row in sheet.iter_rows(min_row=2, values_only=True)
    }


def test_xlsx_preserves_literal_text_precision_long_answers_and_portable_table():
    questions = [question(label="Name"), question("multiple_choice", label="Track")]
    columns = [
        {"id": "score", "label": "Score", "type": "number"},
        {"id": "large", "label": "Large number", "type": "number"},
        {"id": "day", "label": "Date", "type": "date"},
        {"id": "flag", "label": "Checked", "type": "checkbox"},
        {"id": "formula", "label": "=1+1", "type": "text"},
    ]
    long = "Long answer 🎓\n" * 100
    page = export_page(
        questions,
        columns,
        [
            {
                "student_id": "00000001",
                "name": "Student\x00 Name",
                "telegram_id": 100,
                "telegram_username": "student_100",
                "email": "student@example.test",
                "phone_number": "+998901234567",
                "education_level": "Level 4",
                "registration_id": 200,
                "registered_at": datetime(2026, 10, 27, tzinfo=timezone.utc),
                "row_revision": 5,
                "answers": {questions[0]["id"]: long, questions[1]["id"]: ["Option A", "Option B"]},
                "organizer_values": {
                    "score": "8.5",
                    "large": "100000000000000000000000000000000000001",
                    "day": "2026-10-27",
                    "flag": False,
                    "formula": '=HYPERLINK("https://example.test")',
                },
            }
        ],
    )
    content = participants_xlsx(page)
    book = workbook(content)
    sheet = book["Participants"]
    assert sheet.freeze_panes == "C2"
    assert sheet.max_row == 2 and sheet.max_column == 18
    assert [cell.value for cell in sheet[1]][6:13] == [
        "Name (2)",
        "Track",
        "Score",
        "Large number",
        "Date",
        "Checked",
        "=1+1",
    ]
    assert sheet["A2"].value == "00000001" and sheet["A2"].data_type == "s"
    assert sheet["B2"].value == "Student Name"
    assert sheet["E2"].value == "+998901234567" and sheet["E2"].data_type == "s"
    assert sheet["G2"].value == long and sheet["G2"].alignment.wrap_text
    assert sheet["H2"].value == "Option A\nOption B"
    assert sheet["I2"].value == 8.5 and sheet["I2"].data_type == "n"
    assert sheet["J2"].value == page.members[0]["organizer_values"]["large"]
    assert sheet["K2"].value.date() == date(2026, 10, 27)
    assert sheet["L2"].value is False
    assert all(cell.data_type != "f" for row in sheet for cell in row)
    assert sheet["M2"].value.startswith("=HYPERLINK")
    table = sheet.tables["Participants"]
    assert table.ref == "A1:R2" and table.autoFilter.ref == table.ref
    assert [column.name for column in table.tableColumns] == [cell.value for cell in sheet[1]]
    with ZipFile(BytesIO(content)) as archive:
        assert not any(
            "vbaProject" in name or "externalLinks" in name for name in archive.namelist()
        )
    book.close()


def test_xlsx_exposes_versioned_metadata_stable_keys_and_lossless_choice_lists():
    options = ["First\nsecond line", '=HYPERLINK("https://example.test")', "Зеленый 🌱"]
    q = {**question("multiple_choice", label="_SR_TELEGRAM_ID"), "options": options}
    column = {"id": str(uuid4()), "label": "_sr_telegram_id", "type": "text"}
    members = [
        {
            "student_id": str(i).zfill(8),
            "name": f"Student {i}",
            "telegram_id": 2**63 - i,
            "telegram_username": None,
            "email": "student@example.test",
            "phone_number": "+998901234567",
            "education_level": "CIFS",
            "registration_id": 2**63 - i - 100,
            "registered_at": datetime(2026, 10, 27, 12, tzinfo=timezone(timedelta(hours=5))),
            "row_revision": i,
            "answers": {q["id"]: options[:i]},
            "organizer_values": {column["id"]: "=1+1"},
        }
        for i in (1, 2)
    ]
    page = export_page([q], [column], members)
    page.event.title = '=HYPERLINK("https://example.test")'
    page.event.department = "=1+1\x00"
    now = datetime(2026, 11, 10, 15, 20, tzinfo=timezone(timedelta(hours=5)))
    book = workbook(participants_xlsx(page, clock=lambda: now))
    assert book.sheetnames == ["Participants", "Export info", "Columns"]
    assert book.active.title == "Participants"
    assert all(sheet.sheet_state == "visible" for sheet in book)
    metadata = manifest(book)
    assert metadata["format"] == FORMAT and metadata["schema_version"] == SCHEMA_VERSION
    assert str(UUID(metadata["export_id"])) == metadata["export_id"]
    assert metadata["exported_at_utc"] == "2026-11-10T10:20:00Z"
    assert metadata["event_id"] == page.event.id
    assert metadata["event_title"] == page.event.title and metadata["department"] == "=1+1"
    assert metadata["organizer_telegram_id"] == str(2**63 - 1)
    assert metadata["form_revision"] == 2 and metadata["columns_revision"] == 4
    assert metadata["export_scope"] == "selected" and metadata["participant_count"] == 2

    mapping = column_map(book)
    sheet = book[metadata["participants_sheet"]]
    assert len(mapping) == sheet.max_column
    assert len({cell.value.casefold() for cell in sheet[1]}) == sheet.max_column
    assert mapping["system:telegram_id"]["Header"] == "_sr_telegram_id"
    assert mapping[f"display:answer:{q['id']}"]["Header"] == "_SR_TELEGRAM_ID (2)"
    assert mapping[f"column:{column['id']}"]["Header"] == "_sr_telegram_id (3)"
    raw = mapping[f"answer:{q['id']}"]
    assert raw["Encoding"] == "json" and raw["Hidden"] is True
    assert json.loads(raw["Options JSON"]) == options and raw["Required"] is True

    # Import by semantic key and actual header, not display name or column position.
    # Reverse the complete rows as Excel would when sorting its structured table.
    rows = list(sheet.iter_rows(min_row=2, values_only=True))
    for index, row in enumerate(reversed(rows), 2):
        for cell, value in zip(sheet[index], row, strict=True):
            cell.value = value
            if isinstance(value, str):
                cell.data_type = "s"
    by_header = {cell.value: cell.column for cell in sheet[1]}
    for row, member in zip(range(2, 4), reversed(members), strict=True):
        values = {
            key: sheet.cell(row, by_header[field["Header"]]).value for key, field in mapping.items()
        }
        assert values["contact:student_id"] == member["student_id"]
        assert values["system:telegram_id"] == str(member["telegram_id"])
        assert values["system:registration_id"] == str(member["registration_id"])
        assert values["system:registered_at_utc"] == "2026-10-27T07:00:00Z"
        assert values["system:row_revision"] == member["row_revision"]
        assert json.loads(values[f"answer:{q['id']}"]) == member["answers"][q["id"]]
    for field in mapping.values():
        assert sheet.column_dimensions[field["Column"]].hidden == field["Hidden"]
    assert sheet.tables["Participants"].ref == f"A1:{get_column_letter(sheet.max_column)}3"
    assert all(cell.data_type != "f" for tab in book for row in tab for cell in row)
    assert "Export info" in sheet["A1"].comment.text
    book.close()
    another = workbook(participants_xlsx(page, clock=lambda: now))
    assert manifest(another)["export_id"] != metadata["export_id"]
    another.close()


@pytest.mark.asyncio
async def test_export_contains_every_page_current_cells_and_excludes_expired_answers(
    miniapp_client, repository
):
    client = miniapp_client
    event = await client.events.settings(100, client.event_id)
    q = question(label="Experience")
    event = await client.events.configure(100, event.id, configuration(event, questions=[q]))
    for user_id in range(1000, 1012):
        await repository.touch_user(User(id=user_id, is_bot=False, first_name="Student"))
        await complete_student_registration(
            repository,
            user_id,
            Student(
                str(user_id).zfill(8),
                f"Student {user_id}",
                f"{user_id}@example.test",
                account=f"{user_id}@example.test",
            ),
        )
        await client.events.submit_form(
            user_id, event.id, {q["id"]: f"Response {user_id}"}, event.form_revision
        )
    column = {"id": str(uuid4()), "label": "Score", "type": "number", "options": []}
    table = EventTable(repository.db, clock=repository.clock)
    await table.columns(100, event.id, [column], 1)
    await table.edit(
        100,
        event.id,
        1011,
        {
            "scope": "column",
            "field": column["id"],
            "value": "9",
            "revision": 1,
            "columns_revision": 2,
        },
    )
    path = f"/api/forms/{event.id}/members.xlsx"
    response = await client.get(path + "?page=1", headers=headers())
    assert response.status == 200 and response.content_type == XLSX_CONTENT_TYPE
    assert response.headers["Cache-Control"] == "no-store"
    assert (
        response.headers["Content-Disposition"]
        == f'attachment; filename="participants-{event.id}.xlsx"'
    )
    book = workbook(await response.read())
    sheet = book.active
    assert sheet.max_row == 13
    assert sheet["A2"].value == "00001000" and sheet["A13"].value == "00001011"
    assert sheet["G13"].value == "Response 1011" and sheet["H13"].value == 9
    assert manifest(book)["event_id"] == event.id
    assert manifest(book)["export_scope"] == "all"
    assert manifest(book)["participant_count"] == 12
    assert len((await client.events.answer_page(100, event.id)).members) == 10
    book.close()
    selected = await client.events.export_members(100, event.id, member_ids=[1011, 1000])
    assert selected.total == 2
    book = workbook(participants_xlsx(selected))
    assert book.active.max_row == 3
    assert book.active["A2"].value == "00001000"
    assert book.active["A3"].value == "00001011"
    assert book.active["G3"].value == "Response 1011" and book.active["H3"].value == 9
    assert manifest(book)["export_scope"] == "selected"
    assert manifest(book)["participant_count"] == 2
    mapping = column_map(book)
    telegram_column = mapping["system:telegram_id"]["Column"]
    assert book.active[f"{telegram_column}2"].value == "1000"
    assert book.active[f"{telegram_column}3"].value == "1011"
    assert mapping[f"answer:{q['id']}"]["Header"] == "Experience"
    assert mapping[f"column:{column['id']}"]["Header"] == "Score"
    book.close()
    repository.test_clock[0] += timedelta(days=31)
    response = await client.get(path, headers=headers())
    book = workbook(await response.read())
    assert book.active.max_row == 13
    assert all(
        book.active.cell(row, column).value is None for row in range(2, 14) for column in (7, 8)
    )
    book.close()


@pytest.mark.asyncio
async def test_hidden_choice_data_obeys_expiration_and_does_not_change_members_api(
    miniapp_client, repository
):
    client = miniapp_client
    q = question("multiple_choice", label="Track")
    event = await client.events.settings(100, client.event_id)
    event = await client.events.configure(100, event.id, configuration(event, questions=[q]))
    await client.events.submit_form(200, event.id, {q["id"]: ["Option B"]}, event.form_revision)
    path = f"/api/forms/{event.id}/members"
    response = await client.get(path, headers=headers())
    assert response.status == 200
    public_member = (await response.json())["members"][0]
    assert "registration_id" not in public_member and "registered_at" not in public_member

    page = await client.events.export_members(100, event.id, member_ids=[200])
    assert page.members[0]["registered_at"].tzinfo is not None
    book = workbook(participants_xlsx(page))
    mapping = column_map(book)
    raw_column = mapping[f"answer:{q['id']}"]["Column"]
    assert json.loads(book.active[f"{raw_column}2"].value) == ["Option B"]
    assert manifest(book)["export_scope"] == "selected"  # All rows explicitly checked.
    book.close()

    repository.test_clock[0] += timedelta(days=31)
    page = await client.events.export_members(100, event.id, member_ids=[200])
    book = workbook(participants_xlsx(page))
    assert book.active[f"{raw_column}2"].value is None
    assert book.active["G2"].value is None
    assert book.active[f"{mapping['system:telegram_id']['Column']}2"].value == "200"
    assert manifest(book)["participant_count"] == 1
    book.close()


@pytest.mark.asyncio
async def test_empty_export_is_valid_and_download_requires_signed_owner(miniapp_client):
    client = miniapp_client
    assert (
        await client.get(
            f"/api/forms/{client.event_id}/members.xlsx?user_id=100", headers=headers(200)
        )
    ).status == 403
    await client.events.create(200, "Another organizer")
    for resource in ("forms", "events"):
        path = f"/api/{resource}/{client.event_id}/members.xlsx"
        assert (await client.get(path)).status == 401
        assert (await client.get(path + "?user_id=100", headers=headers(200))).status == 400
        response = await client.get(path, headers=headers())
        assert response.status == 200
        book = workbook(await response.read())
        assert book.active.max_row == 1 and book.active["A1"].value == "Student ID"
        assert manifest(book)["participant_count"] == 0
        assert manifest(book)["event_id"] == client.event_id
        book.close()


@pytest.mark.asyncio
async def test_export_runs_off_loop_rejects_overlapping_work_and_releases_slot(
    miniapp_client, monkeypatch
):
    client = miniapp_client
    started, release = Event(), Event()

    def writer(page):
        started.set()
        assert release.wait(timeout=5)
        return participants_xlsx(page)

    monkeypatch.setattr(participant_export, "participants_xlsx", writer)
    path = f"/api/forms/{client.event_id}/members.xlsx"
    task = asyncio.create_task(client.get(path, headers=headers()))
    try:
        assert await asyncio.to_thread(started.wait, 3)
        health = await asyncio.wait_for(client.get("/health"), timeout=1)
        assert health.status == 200
        assert (await client.get(path, headers=headers())).status == 429
    finally:
        release.set()
    response = await task
    assert response.status == 200 and (await response.read()).startswith(b"PK")
    assert not client.server.app[EXPORT_LOCK].locked()


@pytest.mark.asyncio
async def test_export_keeps_slot_until_cancelled_writer_finishes_and_does_not_block_loop(
    monkeypatch,
):
    started, release = asyncio.Event(), asyncio.Event()

    async def writer(*args):
        started.set()
        await release.wait()
        return b"xlsx"

    monkeypatch.setattr(participant_export.asyncio, "to_thread", writer)
    lock = asyncio.Lock()
    request = SimpleNamespace(
        app={
            EXPORT_LOCK: lock,
            REPOSITORY: SimpleNamespace(
                export_members=AsyncMock(
                    return_value=SimpleNamespace(event=SimpleNamespace(id=str(uuid4())))
                )
            ),
        },
        match_info={"event_id": str(uuid4())},
    )

    class Request:
        app = request.app
        match_info = request.match_info

        def __getitem__(self, key):
            assert key is USER
            return 100

    task = asyncio.create_task(export_routes.export_participants(Request()))
    await started.wait()
    assert lock.locked()
    task.cancel()
    await asyncio.sleep(0)
    assert lock.locked()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not lock.locked()
