"""A bounded, immutable set of participant identities for one explicit export."""

from uuid import UUID

from app.event_errors import EventError
from app.models import EventRegistration


def member_id(value):
    if type(value) is int and 0 < value < 2**63:
        return value
    if isinstance(value, str):
        try:
            return str(UUID(value))
        except ValueError:
            pass
    raise EventError("Choose a valid response")


def selected_member_ids(values):
    if not isinstance(values, (list, tuple)) or not 1 <= len(values) <= 2000:
        raise EventError("Select 1 to 2000 different participants to export")
    normalized = tuple(member_id(value) for value in values)
    if len(set(normalized)) != len(normalized) or len({type(value) for value in normalized}) != 1:
        raise EventError("Select different responses from the same form")
    return tuple(sorted(normalized))


def member_condition(event, values):
    values = selected_member_ids(values)
    if any(isinstance(value, str) != event.anonymous for value in values):
        raise EventError("Choose only responses registered for this form")
    column = (
        EventRegistration.anonymous_id if event.anonymous else EventRegistration.telegram_user_id
    )
    return column.in_(values)
