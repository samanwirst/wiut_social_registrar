from sqlalchemy import select

from app.event_errors import EventError
from app.models import Event, TelegramUser
from app.registration_state import registration_complete


async def require_registered(session, user_id):
    user = await session.get(TelegramUser, user_id)
    if not registration_complete(user):
        raise EventError("Complete registration first. Send /start to see the next step.")
    return user


async def owned_event(
    session,
    user_id,
    event_id,
    *,
    lock=False,
    denied="Only the event organizer can manage this event.",
):
    await require_registered(session, user_id)
    query = select(Event).where(Event.id == event_id, Event.creator_telegram_user_id == user_id)
    event = await session.scalar(query.with_for_update() if lock else query)
    if event is None:
        raise EventError(denied)
    return event
