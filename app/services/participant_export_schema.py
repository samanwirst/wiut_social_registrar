"""Versioned, documented field identities for portable participant workbooks."""

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from uuid import uuid4

FORMAT = "wiut-social-registrar.participants"
SCHEMA_VERSION = 1
CONTACTS = (
    ("student_id", "Student ID"),
    ("name", "Name"),
    ("telegram", "Telegram"),
    ("email", "Email"),
    ("phone_number", "Phone"),
    ("education_level", "Level"),
)


@dataclass(frozen=True)
class ExportColumn:
    key: str
    label: str
    scope: str
    field_id: str
    kind: str
    encoding: str = "text"
    hidden: bool = False
    options: tuple[str, ...] = ()
    required: bool | None = None


def utc_timestamp(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        raise ValueError("Export timestamps must include a timezone")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def export_columns(event):
    anonymous = getattr(event, "anonymous", False)
    columns = (
        [
            ExportColumn(
                "system:response_number",
                "Response",
                "system",
                "response_number",
                "number",
                "number_or_text",
            )
        ]
        if anonymous
        else [
            ExportColumn(f"contact:{key}", label, "contact", key, "text") for key, label in CONTACTS
        ]
    )
    raw_choices = []
    for scope, definitions in (("answer", event.questions), ("column", event.table_columns)):
        for item in definitions:
            kind, key = item["type"], f"{scope}:{item['id']}"
            encoding = {
                "number": "number_or_text",
                "date": "excel_date",
                "checkbox": "boolean",
                "multiple_choice": "json",
            }.get(kind, "text")
            column = ExportColumn(
                key,
                item["label"],
                scope,
                item["id"],
                kind,
                encoding,
                options=tuple(item.get("options", [])),
                required=item.get("required"),
            )
            if kind == "multiple_choice":
                # The readable newline-joined cell is ambiguous if an option contains
                # a newline. Keep its exact list in a separate, hidden JSON cell.
                raw_choices.append(replace(column, label=f"_sr_{scope}_{item['id']}", hidden=True))
                column = replace(
                    column, key=f"display:{key}", scope=f"{scope}_display", encoding="lines"
                )
            columns.append(column)
    if anonymous:
        return [*columns, *raw_choices]
    columns.extend(
        ExportColumn(f"system:{key}", label, "system", key, kind, encoding, hidden=True)
        for key, label, kind, encoding in (
            ("telegram_id", "_sr_telegram_id", "text", "text"),
            ("registration_id", "_sr_registration_id", "text", "text"),
            ("registered_at_utc", "_sr_registered_at_utc", "utc_datetime", "iso8601"),
            ("row_revision", "_sr_row_revision", "number", "number_or_text"),
        )
    )
    return [*columns, *raw_choices]


def export_info(page, exported_at):
    """One key/value table, with descriptions usable without reading the source code."""
    event = page.event
    if getattr(event, "anonymous", False):
        return [
            (
                "format",
                "wiut-social-registrar.anonymous-responses",
                "Anonymous response workbook; not an identified participant list",
            ),
            ("schema_version", SCHEMA_VERSION, "Import contract version"),
            ("export_id", str(uuid4()), "Unique ID for this generated file"),
            ("exported_at_utc", utc_timestamp(exported_at), "File generation time in UTC"),
            ("event_id", event.id, "Form UUID"),
            ("event_title", event.title, "Form name"),
            (
                "anonymous",
                True,
                "Student identities and contact fields are excluded, including hidden columns",
            ),
            ("participant_count", len(page.members), "Number of anonymous responses"),
            ("export_scope", page.export_scope, "Selected responses or all responses"),
            (
                "participants_sheet",
                "Participants",
                "Answers and organizer columns only; Response is a row number, not a student ID",
            ),
            ("columns_sheet", "Columns", "Column definitions and answer options"),
        ]
    return [
        ("format", FORMAT, "Workbook format identifier"),
        ("schema_version", SCHEMA_VERSION, "Import contract version"),
        ("export_id", str(uuid4()), "Unique ID for this generated file"),
        ("exported_at_utc", utc_timestamp(exported_at), "File generation time in UTC"),
        ("source", "WIUT Social Registrar", "Application that generated this file"),
        ("event_id", event.id, "Stable form/event UUID, unchanged when its name changes"),
        ("event_title", event.title, "Form/event name at export time"),
        ("department", event.department, "Organizer's department, if supplied"),
        (
            "organizer_telegram_id",
            str(event.creator_telegram_user_id),
            "Telegram user ID of the form owner, stored as text",
        ),
        ("event_created_at_utc", utc_timestamp(event.created_at), "Form creation time in UTC"),
        ("event_revision", event.revision, "Form settings revision at export time"),
        ("form_revision", event.form_revision, "Question definition revision at export time"),
        ("columns_revision", event.columns_revision, "Organizer column definition revision"),
        ("export_scope", page.export_scope, "selected = checked rows; all = entire form"),
        ("participant_count", len(page.members), "Data rows in this file, excluding the header"),
        ("participants_sheet", "Participants", "Readable table and hidden technical columns"),
        ("columns_sheet", "Columns", "Column headers, stable keys, types and choice options"),
        (
            "participant_key",
            "event_id + system:telegram_id",
            "Identify a participant by this pair, never by row position or username",
        ),
        (
            "technical_columns",
            "Unhide columns in Participants to read the technical cells",
            "These columns move with their participant when the table is sorted",
        ),
    ]
