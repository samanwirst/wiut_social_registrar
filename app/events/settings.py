from uuid import uuid4

from sqlalchemy import select

from app.clock import utc_now
from app.event_errors import EventError
from app.events.access import owned_event, require_registered
from app.events.retention import shorten_answer_retention
from app.events.validation import EventChanges, event_title
from app.models import (
    Event,
    TelegramUser,
)
from app.registration_state import registration_complete


class EventSettingsRepository:
    """Event ownership, creation, and revision-controlled settings."""

    def __init__(self, database, *, clock=utc_now):
        self.db = database
        self.clock = clock

    async def is_organizer(self, user_id):
        async with self.db.transaction() as session:
            return (
                await session.scalar(
                    select(Event.id).where(Event.creator_telegram_user_id == user_id).limit(1)
                )
                is not None
            )

    async def require_organizer(self, user_id):
        async with self.db.transaction() as session:
            await require_registered(session, user_id)
            event_id = await session.scalar(
                select(Event.id).where(Event.creator_telegram_user_id == user_id).limit(1)
            )
            if event_id is None:
                raise EventError(
                    "Create your first event with /new_event Event name to unlock the event panel."
                )

    async def create(self, user_id, title="New Event") -> Event:
        title = event_title(title)
        async with self.db.transaction(write=True) as session:
            user = await session.scalar(
                select(TelegramUser).where(TelegramUser.id == user_id).with_for_update()
            )
            if not registration_complete(user):
                raise EventError(
                    "Complete registration first. Send /start to confirm your student details."
                )
            event = Event(
                id=str(uuid4()),
                title=title,
                creator_telegram_user_id=user_id,
                created_at=self.clock(),
            )
            session.add(event)
        return event

    async def settings(self, user_id, event_id):
        async with self.db.transaction() as session:
            return await owned_event(session, user_id, event_id)

    async def configure(self, user_id, event_id, data):
        changes = EventChanges.parse(data)
        questions, retention = changes.questions, changes.response_retention_days
        async with self.db.transaction(write=True) as session:
            event = await owned_event(session, user_id, event_id, lock=True)
            if changes.revision != event.revision:
                raise EventError("This event changed in another window. Reload it before saving.")
            if event.form_locked and questions != event.questions:
                raise EventError(
                    "Questions are locked after the first submission to preserve answer meanings."
                )
            if retention < event.response_retention_days:
                await shorten_answer_retention(session, event.id, retention)
            event.title = changes.title
            event.description = changes.description
            event.registration_open = changes.registration_open
            event.response_retention_days = retention
            if event.questions != questions:
                event.form_revision += 1
            event.questions = questions
            event.revision += 1
        return event
