from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.education import EDUCATION_LEVELS
from app.event_errors import EventError
from app.event_forms import validate_answers, validate_questions
from app.models import Event, EventAnswers, EventFormSession, EventRegistration, OutlookProfile, PendingEventRegistration, TelegramUser


@dataclass(frozen=True)
class OwnedEventsPage:
    events: list[Event]
    total: int
    page: int
    pages: int


@dataclass(frozen=True)
class MembersPage:
    event: Event
    total: int
    page: int
    pages: int
    members: list[dict]


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


def _registered(user):
    return (user is not None and user.registered_at is not None and user.verified_at is not None
            and user.phone_number is not None and user.outlook_profile_id is not None
            and user.education_level in EDUCATION_LEVELS.values())


async def _enroll(session, insert, user, event_id, now) -> bool:
    result = await session.execute(insert(EventRegistration).values(
        event_id=event_id, telegram_user_id=user.id, outlook_profile_id=user.outlook_profile_id,
        registered_at=now,
    ).on_conflict_do_nothing().returning(EventRegistration.id))
    return result.scalar_one_or_none()


async def _existing_registration(session, user, event_id):
    return await session.scalar(select(EventRegistration).where(
        EventRegistration.event_id == event_id,
        or_(EventRegistration.telegram_user_id == user.id,
            EventRegistration.outlook_profile_id == user.outlook_profile_id)))


async def enroll_pending_events(session, insert, user, now):
    """Called inside the same transaction that completes the student's registration."""
    if not _registered(user):
        return
    event_ids = list((await session.scalars(select(PendingEventRegistration.event_id).where(
        PendingEventRegistration.telegram_user_id == user.id).order_by(PendingEventRegistration.event_id))).all())
    for event_id in event_ids:
        event = await session.scalar(select(Event).where(Event.id == event_id).with_for_update())
        existing = await _existing_registration(session, user, event_id)
        if event.questions and event.registration_open and existing is None:
            continue
        if event.registration_open and existing is None:
            await _enroll(session, insert, user, event_id, now)
        await session.execute(delete(PendingEventRegistration).where(
            PendingEventRegistration.telegram_user_id == user.id, PendingEventRegistration.event_id == event_id))


class EventRepository:
    EVENTS_PAGE_SIZE = 5
    MEMBERS_PAGE_SIZE = 10

    def __init__(self, database, *, clock=None):
        self.db = database
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.insert = sqlite_insert if database.engine.dialect.name == "sqlite" else pg_insert

    async def is_organizer(self, user_id):
        async with self.db.transaction() as session:
            return await session.scalar(select(Event.id).where(
                Event.creator_telegram_user_id == user_id).limit(1)) is not None

    async def require_organizer(self, user_id):
        async with self.db.transaction() as session:
            await self._require_registered(session, user_id)
            event_id = await session.scalar(select(Event.id).where(
                Event.creator_telegram_user_id == user_id).limit(1))
            if event_id is None:
                raise EventError("Create your first event with /new_event Event name to unlock the event panel.")

    async def create(self, user_id, title="New Event") -> Event:
        title = " ".join(title.split())
        if not title or len(title) > 200:
            raise EventError("Event names must contain 1 to 200 characters.")
        async with self.db.transaction(write=True) as session:
            user = await session.scalar(select(TelegramUser).where(TelegramUser.id == user_id).with_for_update())
            if not _registered(user):
                raise EventError("Complete registration first. Send /start to confirm your student details.")
            event = Event(id=str(uuid4()), title=title, creator_telegram_user_id=user_id, created_at=self.clock())
            session.add(event)
        return event

    async def visit(self, user_id, event_id):
        async with self.db.transaction(write=True) as session:
            user = await session.scalar(select(TelegramUser).where(TelegramUser.id == user_id).with_for_update())
            event = await session.scalar(select(Event).where(Event.id == event_id).with_for_update())
            if event is None:
                raise EventError("This event does not exist. Ask the organizer for a valid QR code.")
            if user is None:
                raise EventError("Send /start to begin registration.")
            existing = await _existing_registration(session, user, event_id) if _registered(user) else None
            if not event.registration_open and not existing:
                raise EventError("Registration for this event is closed.")
            if _registered(user):
                if event.questions and existing is None:
                    await session.execute(self.insert(PendingEventRegistration).values(
                        telegram_user_id=user_id, event_id=event.id, requested_at=self.clock(),
                    ).on_conflict_do_nothing())
                    return event, "needs_form"
                created = await _enroll(session, self.insert, user, event.id, self.clock()) if existing is None else None
                await session.execute(delete(PendingEventRegistration).where(
                    PendingEventRegistration.telegram_user_id == user_id, PendingEventRegistration.event_id == event.id))
                status = "registered" if created else "already_registered"
            else:
                await session.execute(self.insert(PendingEventRegistration).values(
                    telegram_user_id=user_id, event_id=event.id, requested_at=self.clock(),
                ).on_conflict_do_nothing())
                status = "pending"
        return event, status

    async def pending_titles(self, user_id, *, limit=10):
        async with self.db.transaction() as session:
            return list((await session.scalars(select(Event.title).join(
                PendingEventRegistration, PendingEventRegistration.event_id == Event.id).where(
                    PendingEventRegistration.telegram_user_id == user_id).order_by(
                        PendingEventRegistration.requested_at, PendingEventRegistration.event_id).limit(limit))).all())

    async def pending_forms(self, user_id):
        async with self.db.transaction() as session:
            events = list((await session.scalars(select(Event).join(
                PendingEventRegistration, PendingEventRegistration.event_id == Event.id).where(
                    PendingEventRegistration.telegram_user_id == user_id, Event.registration_open.is_(True)).order_by(
                        PendingEventRegistration.requested_at, Event.id))).all())
            return [event for event in events if event.questions]

    async def _require_registered(self, session, user_id):
        user = await session.get(TelegramUser, user_id)
        if not _registered(user):
            raise EventError("Complete registration first. Send /start to see the next step.")
        return user

    async def _owned(self, session, user_id, event_id, *, lock=False):
        await self._require_registered(session, user_id)
        query = select(Event).where(Event.id == event_id, Event.creator_telegram_user_id == user_id)
        event = await session.scalar(query.with_for_update() if lock else query)
        if event is None:
            raise EventError("Only the event organizer can manage this event.")
        return event

    async def settings(self, user_id, event_id):
        async with self.db.transaction() as session:
            return await self._owned(session, user_id, event_id)

    async def configure(self, user_id, event_id, data):
        if not isinstance(data, dict) or set(data) != {
                "title", "description", "registration_open", "response_retention_days", "questions", "revision"}:
            raise EventError("Submit the event title, description, status, retention, questions, and revision.")
        title, description = data["title"], data["description"]
        if not isinstance(title, str) or not 1 <= len(" ".join(title.split())) <= 200:
            raise EventError("Event names must contain 1 to 200 characters.")
        if not isinstance(description, str) or len(description) > 4000:
            raise EventError("Use at most 4000 characters for the description.")
        retention = data["response_retention_days"]
        if type(retention) is not int or not 1 <= retention <= 90:
            raise EventError("Keep answers for 1 to 90 days.")
        if not isinstance(data["registration_open"], bool) or type(data["revision"]) is not int:
            raise EventError("Supply a valid registration status and revision.")
        questions = validate_questions(data["questions"])
        async with self.db.transaction(write=True) as session:
            event = await self._owned(session, user_id, event_id, lock=True)
            if data["revision"] != event.revision:
                raise EventError("This event changed in another window. Reload it before saving.")
            if event.form_locked and questions != event.questions:
                raise EventError("Questions are locked after the first submission to preserve answer meanings.")
            if retention < event.response_retention_days:
                responses = (await session.scalars(select(EventAnswers).join(
                    EventRegistration, EventRegistration.id == EventAnswers.registration_id).where(
                        EventRegistration.event_id == event.id))).all()
                for response in responses:
                    response.expires_at = min(response.expires_at, response.submitted_at + timedelta(days=retention))
            event.title = " ".join(title.split())
            event.description = description.strip()
            event.registration_open = data["registration_open"]
            event.response_retention_days = retention
            if event.questions != questions:
                event.form_revision += 1
            event.questions = questions
            event.revision += 1
        return event

    async def submit_form(self, user_id, event_id, answers, form_revision):
        async with self.db.transaction(write=True) as session:
            user = await session.scalar(select(TelegramUser).where(TelegramUser.id == user_id).with_for_update())
            if not _registered(user):
                raise EventError("Complete student registration in the bot first. Send /start to continue.")
            event = await session.scalar(select(Event).where(Event.id == event_id).with_for_update())
            if event is None:
                raise EventError("This event does not exist.")
            return event, await self._submit_form(session, user, event, answers, form_revision)

    async def _submit_form(self, session, user, event, answers, form_revision):
        existing = await _existing_registration(session, user, event.id)
        registration_id = None
        if existing is None:
            if not event.registration_open:
                raise EventError("Registration for this event is closed.")
            if type(form_revision) is not int or form_revision != event.form_revision:
                raise EventError("The event form changed. Send /start to load the updated questions.")
            values = validate_answers(event.questions, answers)
            now = self.clock()
            registration_id = await _enroll(session, self.insert, user, event.id, now)
            if registration_id is not None and event.questions:
                event.form_locked = True
                session.add(EventAnswers(registration_id=registration_id, answers=values,
                    submitted_at=now, expires_at=now + timedelta(days=event.response_retention_days)))
        await session.execute(delete(PendingEventRegistration).where(
            PendingEventRegistration.telegram_user_id == user.id, PendingEventRegistration.event_id == event.id))
        return existing is None and registration_id is not None

    async def answer_page(self, user_id, event_id, page=0):
        members = await self.members(user_id, event_id, page)
        async with self.db.transaction() as session:
            rows = (await session.execute(select(EventRegistration.telegram_user_id, EventAnswers).join(
                EventAnswers, EventAnswers.registration_id == EventRegistration.id).where(
                    EventRegistration.event_id == event_id,
                    EventRegistration.telegram_user_id.in_([item["telegram_id"] for item in members.members]),
                    EventAnswers.expires_at > self.clock()))).all()
            answers = {user_id: response for user_id, response in rows}
            for member in members.members:
                response = answers.get(member["telegram_id"])
                member["answers"] = response.answers if response else None
                member["answers_expires_at"] = response.expires_at.isoformat() if response else None
        return members

    async def purge_answers(self, user_id=None, event_id=None):
        async with self.db.transaction(write=True) as session:
            query = delete(EventAnswers)
            if user_id is not None:
                await self._owned(session, user_id, event_id, lock=True)
                query = query.where(EventAnswers.registration_id.in_(select(EventRegistration.id).where(
                    EventRegistration.event_id == event_id)))
                await session.execute(delete(EventFormSession).where(EventFormSession.event_id == event_id))
            else:
                query = query.where(EventAnswers.expires_at <= self.clock())
            result = await session.execute(query)
            await session.execute(delete(EventFormSession).where(EventFormSession.expires_at <= self.clock()))
            return result.rowcount

    async def owned_events(self, user_id, page=0) -> OwnedEventsPage:
        async with self.db.transaction() as session:
            await self._require_registered(session, user_id)
            condition = Event.creator_telegram_user_id == user_id
            total = await session.scalar(select(func.count()).select_from(Event).where(condition))
            pages = max(1, (total + self.EVENTS_PAGE_SIZE - 1) // self.EVENTS_PAGE_SIZE)
            page = min(max(0, page), pages - 1)
            events = list((await session.scalars(select(Event).where(condition).order_by(
                Event.created_at.desc(), Event.id.desc()).offset(page * self.EVENTS_PAGE_SIZE).limit(
                    self.EVENTS_PAGE_SIZE))).all())
            return OwnedEventsPage(events, total, page, pages)

    async def members(self, user_id, event_id, page=0) -> MembersPage:
        async with self.db.transaction() as session:
            await self._require_registered(session, user_id)
            event = await session.get(Event, event_id)
            if event is None or event.creator_telegram_user_id != user_id:
                raise EventError("Only the event organizer can view its members.")
            total = await session.scalar(select(func.count()).select_from(EventRegistration).where(
                EventRegistration.event_id == event.id))
            pages = max(1, (total + self.MEMBERS_PAGE_SIZE - 1) // self.MEMBERS_PAGE_SIZE)
            page = min(max(0, page), pages - 1)
            rows = (await session.execute(select(
                OutlookProfile.student_id.label("student_id"), OutlookProfile.display_name.label("name"),
                TelegramUser.id.label("telegram_id"), TelegramUser.username.label("telegram_username"),
                OutlookProfile.email.label("email"), TelegramUser.phone_number.label("phone_number"),
                TelegramUser.education_level.label("education_level"),
            ).select_from(EventRegistration).join(
                TelegramUser, TelegramUser.id == EventRegistration.telegram_user_id).join(
                OutlookProfile, OutlookProfile.id == EventRegistration.outlook_profile_id).where(
                    EventRegistration.event_id == event.id).order_by(
                        EventRegistration.registered_at, EventRegistration.id).offset(page * self.MEMBERS_PAGE_SIZE).limit(
                            self.MEMBERS_PAGE_SIZE))).mappings().all()
            return MembersPage(event, total, page, pages, [dict(row) for row in rows])
