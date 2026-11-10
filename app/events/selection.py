"""A bounded, immutable set of participant identities for one explicit export."""

from app.event_errors import EventError


def selected_member_ids(values):
    if (
        not isinstance(values, (list, tuple))
        or not 1 <= len(values) <= 2000
        or any(type(value) is not int or not 0 < value < 2**63 for value in values)
        or len(set(values)) != len(values)
    ):
        raise EventError("Select 1 to 2000 different participants to export")
    return tuple(sorted(values))
