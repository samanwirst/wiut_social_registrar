from uuid import UUID

from app.event_errors import EventError


def event_id_from_payload(payload: str) -> str:
    try:
        if not payload.startswith("event_"):
            raise ValueError
        value = UUID(payload[6:])
        if str(value) != payload[6:].lower() or value.version != 4:
            raise ValueError
        return str(value)
    except ValueError:
        raise EventError("This event link is invalid.") from None
