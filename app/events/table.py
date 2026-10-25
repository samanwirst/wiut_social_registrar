"""Owned, optimistic table edits with the same temporary-data retention as responses."""

from datetime import timedelta

from sqlalchemy import select

from app.clock import utc_now
from app.event_errors import EventError
from app.event_forms import validate_answers
from app.events.access import owned_event
from app.models import EventAnswers, EventRegistration, EventTableValues
from app.table_fields import column_value, validate_columns


class EventTable:
    def __init__(self, database, *, clock=utc_now):
        self.db, self.clock = database, clock

    async def columns(self, owner, event_id, columns, revision):
        columns = validate_columns(columns)
        if type(revision) is not int:
            raise EventError("Supply the current column revision")
        async with self.db.transaction(write=True) as session:
            event = await owned_event(session, owner, event_id, lock=True)
            if revision != event.columns_revision:
                raise EventError("Columns changed in another window — refresh the table")
            previous = {c["id"]: c for c in event.table_columns}
            current = {c["id"]: c for c in columns}
            if any(
                previous[key]["type"] != current[key]["type"]
                for key in previous.keys() & current.keys()
            ):
                raise EventError("Create a new column to change its type")
            removed = previous.keys() - current.keys()
            if removed:
                rows = await session.scalars(
                    select(EventTableValues).where(
                        EventTableValues.registration_id.in_(
                            select(EventRegistration.id).where(
                                EventRegistration.event_id == event_id
                            )
                        )
                    )
                )
                for row in rows:
                    row.values = {
                        key: value for key, value in row.values.items() if key not in removed
                    }
            event.table_columns = columns
            event.columns_revision += 1
            return {"columns": columns, "columns_revision": event.columns_revision}

    async def edit(self, owner, event_id, user_id, data):
        if not isinstance(data, dict) or set(data) != {
            "scope",
            "field",
            "value",
            "revision",
            "columns_revision",
        }:
            raise EventError("Submit one cell with its row and column revisions")
        if (
            type(user_id) is not int
            or not 0 < user_id < 2**63
            or type(data["revision"]) is not int
            or type(data["columns_revision"]) is not int
        ):
            raise EventError("Supply a valid participant and revision")
        scope, key, value = data["scope"], data["field"], data["value"]
        if (
            not isinstance(scope, str)
            or scope not in {"answer", "column"}
            or not isinstance(key, str)
        ):
            raise EventError("Only form responses and organizer columns can be edited")
        async with self.db.transaction(write=True) as session:
            event = await owned_event(session, owner, event_id, lock=True)
            if event.columns_revision != data["columns_revision"]:
                raise EventError("Columns changed in another window — refresh the table")
            registration = await session.scalar(
                select(EventRegistration)
                .where(
                    EventRegistration.event_id == event_id,
                    EventRegistration.telegram_user_id == user_id,
                )
                .with_for_update()
            )
            if registration is None:
                raise EventError("Choose a person registered for this form")
            if registration.table_revision != data["revision"]:
                raise EventError("This row changed in another window — refresh the table")
            expires_at = registration.table_expires_at or registration.registered_at + timedelta(
                days=event.response_retention_days
            )
            if self.clock() >= expires_at:
                raise EventError("The response retention window has expired")
            if scope == "answer":
                question = next((q for q in event.questions if q["id"] == key), None)
                if question is None:
                    raise EventError("Choose a question belonging to this form")
                if (
                    question["type"] == "multiple_choice"
                    and isinstance(value, list)
                    and len(value) > 1
                ):
                    raise EventError(f"Choose one option for: {question['label']}")
                normalized = validate_answers([question], {key: value}).get(key)
                row = await session.get(EventAnswers, registration.id, with_for_update=True)
                if row is not None and row.expires_at <= self.clock():
                    raise EventError("Expired responses cannot be restored")
                if row is None:
                    row = EventAnswers(
                        registration_id=registration.id,
                        answers={},
                        submitted_at=registration.registered_at,
                        expires_at=expires_at,
                    )
                    session.add(row)
                values = dict(row.answers)
                if normalized is None:
                    values.pop(key, None)
                else:
                    values[key] = normalized
                row.answers = values
            else:
                column = next((c for c in event.table_columns if c["id"] == key), None)
                if column is None:
                    raise EventError("Choose a column belonging to this form")
                normalized = column_value(column, value)
                row = await session.get(EventTableValues, registration.id, with_for_update=True)
                if row is None:
                    row = EventTableValues(
                        registration_id=registration.id,
                        values={},
                        updated_at=self.clock(),
                        expires_at=expires_at,
                    )
                    session.add(row)
                if row.expires_at <= self.clock():
                    raise EventError("Expired table values cannot be restored")
                values = dict(row.values)
                if normalized is None:
                    values.pop(key, None)
                else:
                    values[key] = normalized
                row.values = values
                row.updated_at = self.clock()
            registration.table_revision += 1
            return {
                "revision": registration.table_revision,
                "scope": scope,
                "field": key,
                "value": normalized,
            }
