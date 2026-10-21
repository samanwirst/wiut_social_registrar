from datetime import timedelta

from sqlalchemy import delete, or_, select

from app.clock import utc_now
from app.event_errors import EventError
from app.event_forms import validate_answers
from app.models import (
    Event,
    EventAnswers,
    EventRegistration,
    PendingEventRegistration,
    TelegramUser,
)
from app.registration_state import registration_complete


async def enroll(session, insert, user, event_id, now) -> int | None:
    result = await session.execute(
        insert(EventRegistration)
        .values(
            event_id=event_id,
            telegram_user_id=user.id,
            outlook_profile_id=user.outlook_profile_id,
            registered_at=now,
        )
        .on_conflict_do_nothing()
        .returning(EventRegistration.id)
    )
    return result.scalar_one_or_none()


async def existing_registration(session, user, event_id):
    return await session.scalar(
        select(EventRegistration).where(
            EventRegistration.event_id == event_id,
            or_(
                EventRegistration.telegram_user_id == user.id,
                EventRegistration.outlook_profile_id == user.outlook_profile_id,
            ),
        )
    )


async def enroll_pending_events(session, insert, user, now):
    """Called inside the same transaction that completes the student's registration."""
    if not registration_complete(user):
        return
    event_ids = list(
        (
            await session.scalars(
                select(PendingEventRegistration.event_id)
                .where(PendingEventRegistration.telegram_user_id == user.id)
                .order_by(PendingEventRegistration.event_id)
            )
        ).all()
    )
    for event_id in event_ids:
        event = await session.scalar(select(Event).where(Event.id == event_id).with_for_update())
        existing = await existing_registration(session, user, event_id)
        if event.questions and event.registration_open and existing is None:
            continue
        if event.registration_open and existing is None:
            await enroll(session, insert, user, event_id, now)
        await session.execute(
            delete(PendingEventRegistration).where(
                PendingEventRegistration.telegram_user_id == user.id,
                PendingEventRegistration.event_id == event_id,
            )
        )


class EventEnrollment:
    """Invitations, idempotent enrollment, and atomic answer submission."""

    def __init__(self, database, *, clock=utc_now):
        self.db = database
        self.clock = clock
        self.insert = database.insert

    async def visit(self, user_id, event_id):
        async with self.db.transaction(write=True) as session:
            user = await session.scalar(
                select(TelegramUser).where(TelegramUser.id == user_id).with_for_update()
            )
            event = await session.scalar(
                select(Event).where(Event.id == event_id).with_for_update()
            )
            if event is None:
                raise EventError(
                    "This event does not exist. Ask the organizer for a valid QR code."
                )
            if user is None:
                raise EventError("Send /start to begin registration.")
            existing = (
                await existing_registration(session, user, event_id)
                if registration_complete(user)
                else None
            )
            if not event.registration_open and not existing:
                raise EventError("Registration for this event is closed.")
            registered = registration_complete(user)
            if not registered or (event.questions and existing is None):
                await session.execute(
                    self.insert(PendingEventRegistration)
                    .values(
                        telegram_user_id=user_id,
                        event_id=event.id,
                        requested_at=self.clock(),
                    )
                    .on_conflict_do_nothing()
                )
                return event, "needs_form" if registered else "pending"
            created = (
                await enroll(session, self.insert, user, event.id, self.clock())
                if existing is None
                else None
            )
            await session.execute(
                delete(PendingEventRegistration).where(
                    PendingEventRegistration.telegram_user_id == user_id,
                    PendingEventRegistration.event_id == event.id,
                )
            )
            status = "registered" if created else "already_registered"
        return event, status

    async def pending_titles(self, user_id, *, limit=10):
        async with self.db.transaction() as session:
            return list(
                (
                    await session.scalars(
                        select(Event.title)
                        .join(
                            PendingEventRegistration, PendingEventRegistration.event_id == Event.id
                        )
                        .where(PendingEventRegistration.telegram_user_id == user_id)
                        .order_by(
                            PendingEventRegistration.requested_at, PendingEventRegistration.event_id
                        )
                        .limit(limit)
                    )
                ).all()
            )

    async def pending_forms(self, user_id):
        async with self.db.transaction() as session:
            events = list(
                (
                    await session.scalars(
                        select(Event)
                        .join(
                            PendingEventRegistration, PendingEventRegistration.event_id == Event.id
                        )
                        .where(
                            PendingEventRegistration.telegram_user_id == user_id,
                            Event.registration_open.is_(True),
                        )
                        .order_by(PendingEventRegistration.requested_at, Event.id)
                    )
                ).all()
            )
            return [event for event in events if event.questions]

    async def submit_form(self, user_id, event_id, answers, form_revision):
        async with self.db.transaction(write=True) as session:
            user = await session.scalar(
                select(TelegramUser).where(TelegramUser.id == user_id).with_for_update()
            )
            if not registration_complete(user):
                raise EventError(
                    "Complete student registration in the bot first. Send /start to continue."
                )
            event = await session.scalar(
                select(Event).where(Event.id == event_id).with_for_update()
            )
            if event is None:
                raise EventError("This event does not exist.")
            return event, await self.submit_answers_in_transaction(
                session, user, event, answers, form_revision
            )

    async def submit_answers_in_transaction(self, session, user, event, answers, form_revision):
        """Caller owns the transaction and must lock the student, then the event."""
        existing = await existing_registration(session, user, event.id)
        registration_id = None
        if existing is None:
            if not event.registration_open:
                raise EventError("Registration for this event is closed.")
            if type(form_revision) is not int or form_revision != event.form_revision:
                raise EventError(
                    "The event form changed. Send /start to load the updated questions."
                )
            values = validate_answers(event.questions, answers)
            now = self.clock()
            registration_id = await enroll(session, self.insert, user, event.id, now)
            if registration_id is not None and event.questions:
                event.form_locked = True
                session.add(
                    EventAnswers(
                        registration_id=registration_id,
                        answers=values,
                        submitted_at=now,
                        expires_at=now + timedelta(days=event.response_retention_days),
                    )
                )
        await session.execute(
            delete(PendingEventRegistration).where(
                PendingEventRegistration.telegram_user_id == user.id,
                PendingEventRegistration.event_id == event.id,
            )
        )
        return existing is None and registration_id is not None
