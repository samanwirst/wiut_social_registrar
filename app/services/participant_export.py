"""Portable XLSX tables with literal user text and no persistent export files."""

import asyncio
import json
import re
from datetime import date
from decimal import Decimal
from io import BytesIO

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

from app.clock import utc_now
from app.event_errors import EventError
from app.services.participant_export_schema import export_columns, export_info, utc_timestamp

XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
INVALID_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")


async def prepare_participants(repository, owner, event_id, lock, *, member_ids=None):
    async with lock:
        page = await repository.export_members(owner, event_id, member_ids=member_ids)
        job = asyncio.create_task(asyncio.to_thread(participants_xlsx, page))
        try:
            return page.event, await asyncio.shield(job)
        except asyncio.CancelledError:
            # A Python thread cannot be cancelled; keep its slot until it finishes.
            await asyncio.gather(job, return_exceptions=True)
            raise


def text(value):
    return INVALID_XML.sub("", str(value))


def append_row(worksheet, values):
    # openpyxl validates strings while appending, before sheet styling runs.
    worksheet.append([text(value) if isinstance(value, str) else value for value in values])


def headers(labels):
    """Excel table column names must be unique, including case-insensitive duplicates."""
    used, result = set(), []
    for label in labels:
        original = text(label).strip() or "Column"
        candidate, suffix = original, 2
        while candidate.casefold() in used:
            candidate = f"{original} ({suffix})"
            suffix += 1
        used.add(candidate.casefold())
        result.append(candidate)
    return result


def cell_value(value, kind):
    if value is None:
        return None
    if isinstance(value, list):
        return "\n".join(text(item) for item in value)
    if type(value) is bool:
        return value
    if kind == "date":
        return date.fromisoformat(value)
    if kind == "number":
        number = Decimal(value)
        # Excel stores only 15 significant digits. Preserve larger values as text.
        digits = "".join(str(digit) for digit in number.as_tuple().digits).rstrip("0")
        if number.is_finite() and len(digits) <= 15:
            converted = float(number)
            if abs(converted) < float("inf") and (converted != 0 or number == 0):
                return converted
    return text(value)


def member_value(member, column):
    scope, key = column.scope, column.field_id
    if scope == "contact":
        if key == "telegram":
            return (
                "@" + member["telegram_username"]
                if member["telegram_username"]
                else f"tg://user?id={member['telegram_id']}"
            )
        return member[key]
    if scope == "system":
        if key == "registered_at_utc":
            return utc_timestamp(member["registered_at"])
        return member[key] if key == "row_revision" else str(member[key])
    source = member.get("answers") if scope.startswith("answer") else member["organizer_values"]
    value = (source or {}).get(key)
    if column.encoding == "json":
        return json.dumps(value, ensure_ascii=False) if value is not None else None
    return cell_value(value, column.kind)


def format_sheet(worksheet, widths, table_name):
    worksheet.sheet_view.showGridLines = False
    for index, width in enumerate(widths, 1):
        worksheet.column_dimensions[get_column_letter(index)].width = width
    for row in worksheet:
        for cell in row:
            if isinstance(cell.value, str):
                # Never interpret student responses, labels, IDs or contacts as formulas.
                cell.value = text(cell.value)
                cell.data_type = "s"
                cell.number_format = "@"
            elif isinstance(cell.value, date):
                cell.number_format = "yyyy-mm-dd"
            cell.alignment = Alignment(vertical="top", wrap_text=True)
        if row[0].row == 1:
            for cell in row:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="217346")
    last = get_column_letter(worksheet.max_column)
    reference = f"A1:{last}{max(1, worksheet.max_row)}"
    if worksheet.max_row > 1:
        table = Table(displayName=table_name, ref=reference)
        table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium4", showRowStripes=True)
        worksheet.add_table(table)
    else:
        worksheet.auto_filter.ref = reference


def participants_xlsx(page, *, clock=utc_now):
    """Render an already-authorized, expiry-filtered snapshot outside the event loop."""
    if len(page.members) >= 1_048_576:
        raise EventError("This form exceeds the Excel worksheet row limit")
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Participants"
    workbook.properties.title = text(page.event.title)
    workbook.properties.creator = "WIUT Social Registrar"
    definitions = export_columns(page.event)
    # Reserve technical headers before disambiguating user-supplied labels.
    order = sorted(range(len(definitions)), key=lambda i: not definitions[i].hidden)
    resolved = dict(zip(order, headers([definitions[i].label for i in order]), strict=True))
    names = [resolved[i] for i in range(len(definitions))]
    append_row(worksheet, names)
    worksheet.freeze_panes = "C2"
    worksheet["A1"].comment = Comment(
        "Export info and Columns describe this file for import. "
        "Unhide the technical columns to inspect participant IDs.",
        "WIUT Social Registrar",
    )
    for member in page.members:
        append_row(worksheet, [member_value(member, column) for column in definitions])
    format_sheet(worksheet, [16, 30, 24, 36, 22, 16] + [45] * (len(names) - 6), "Participants")
    for index, column in enumerate(definitions, 1):
        worksheet.column_dimensions[get_column_letter(index)].hidden = column.hidden

    info = workbook.create_sheet("Export info")
    append_row(info, ["Key", "Value", "Description"])
    for row in export_info(page, clock()):
        append_row(info, row)
    info.freeze_panes = "B2"
    format_sheet(info, [29, 64, 76], "ExportInfo")

    mapping = workbook.create_sheet("Columns")
    append_row(
        mapping,
        [
            "Column",
            "Header",
            "Key",
            "Scope",
            "Field ID",
            "Type",
            "Encoding",
            "Hidden",
            "Options JSON",
            "Required",
        ],
    )
    for index, column in enumerate(definitions, 1):
        append_row(
            mapping,
            [
                get_column_letter(index),
                names[index - 1],
                column.key,
                column.scope,
                column.field_id,
                column.kind,
                column.encoding,
                column.hidden,
                json.dumps(column.options, ensure_ascii=False) if column.options else None,
                column.required,
            ],
        )
    mapping.freeze_panes = "C2"
    format_sheet(mapping, [12, 38, 48, 20, 40, 20, 20, 12, 64, 12], "ExportColumns")
    output = BytesIO()
    try:
        workbook.save(output)
        return output.getvalue()
    finally:
        workbook.close()
        output.close()
