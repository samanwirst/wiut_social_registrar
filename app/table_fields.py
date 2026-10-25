"""Typed organizer columns and cell validation, independent of transport and SQL."""

import math
from datetime import date
from uuid import UUID

from app.event_errors import EventError

COLUMN_TYPES = {"text", "number", "choice", "checkbox", "date"}


def validate_columns(columns):
    if not isinstance(columns, list) or len(columns) > 20:
        raise EventError("Use at most 20 organizer columns")
    result, seen = [], set()
    for column in columns:
        if not isinstance(column, dict) or set(column) != {"id", "label", "type", "options"}:
            raise EventError("Each column needs an ID, label, type, and options")
        try:
            key = str(UUID(column["id"]))
        except (ValueError, TypeError, AttributeError):
            raise EventError("Each column needs a unique ID") from None
        label, kind, options = column["label"], column["type"], column["options"]
        if key in seen or not isinstance(label, str) or not 1 <= len(label.strip()) <= 100:
            raise EventError("Use unique column IDs and labels of 1 to 100 characters")
        if not isinstance(kind, str) or kind not in COLUMN_TYPES or not isinstance(options, list):
            raise EventError("Choose a supported column type")
        if kind == "choice":
            if not 2 <= len(options) <= 20 or any(
                not isinstance(v, str) or not 1 <= len(v.strip()) <= 100 for v in options
            ):
                raise EventError("Choice columns need 2 to 20 options")
            options = [v.strip() for v in options]
            if len(set(options)) != len(options):
                raise EventError("Column options must be unique")
        elif options:
            raise EventError("Only choice columns accept options")
        seen.add(key)
        result.append({"id": key, "label": label.strip(), "type": kind, "options": options})
    if len({v["label"].casefold() for v in result}) != len(result):
        raise EventError("Column labels must be unique")
    return result


def column_value(column, value):
    if value is None or value == "":
        return None
    kind = column["type"]
    if kind == "checkbox":
        if type(value) is not bool:
            raise EventError("Choose checked or unchecked")
        return value
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 2000:
        raise EventError("Use at most 2000 characters in a cell")
    value = value.strip()
    if kind == "choice" and value not in column["options"]:
        raise EventError("Choose an available column option")
    if kind == "number":
        try:
            if len(value) > 64 or not math.isfinite(float(value)):
                raise ValueError
        except ValueError:
            raise EventError("Enter a finite number") from None
    if kind == "date":
        try:
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError
        except ValueError:
            raise EventError("Choose a date in YYYY-MM-DD format") from None
    return value
