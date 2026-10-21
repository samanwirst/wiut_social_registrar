from datetime import timedelta

from sqlalchemy import delete, select

from app.clock import utc_now
from app.events.access import owned_event
from app.models import (
    EventAnswers,
    EventFormSession,
    EventRegistration,
)


async def shorten_answer_retention(session, event_id, days):
    """Join the existing settings transaction; extending retention never revives answers."""
    responses = (
        await session.scalars(
            select(EventAnswers)
            .join(
                EventRegistration,
                EventRegistration.id == EventAnswers.registration_id,
            )
            .where(EventRegistration.event_id == event_id)
        )
    ).all()
    for response in responses:
        response.expires_at = min(response.expires_at, response.submitted_at + timedelta(days=days))


class EventAnswerRetention:
    """Delete expired event answers and drafts without changing attendance."""

    def __init__(self, database, *, clock=utc_now):
        self.db = database
        self.clock = clock

    async def purge_answers(self, user_id=None, event_id=None):
        async with self.db.transaction(write=True) as session:
            query = delete(EventAnswers)
            if user_id is not None:
                await owned_event(session, user_id, event_id, lock=True)
                query = query.where(
                    EventAnswers.registration_id.in_(
                        select(EventRegistration.id).where(EventRegistration.event_id == event_id)
                    )
                )
                await session.execute(
                    delete(EventFormSession).where(EventFormSession.event_id == event_id)
                )
            else:
                query = query.where(EventAnswers.expires_at <= self.clock())
            result = await session.execute(query)
            await session.execute(
                delete(EventFormSession).where(EventFormSession.expires_at <= self.clock())
            )
            return result.rowcount
