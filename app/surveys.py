import secrets
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import delete, select

from app.event_errors import EventError
from app.event_forms import apply_question_response
from app.events.enrollment import discard_other_pending_events, existing_registration
from app.models import Event, EventFormSession, PendingEventRegistration, TelegramUser
from app.registration_state import registration_complete

FORM_SESSION_TTL = timedelta(hours=1)


@dataclass(frozen=True)
class FormStep:
    event: Event
    token: str
    index: int
    answers: dict

    @property
    def question(self):
        return self.event.questions[self.index]


class EventSurvey:
    """Persist chat progress for one hour; commit enrollment and final answers together."""

    def __init__(self, repository):
        self.repository = repository

    def _step(self, event, draft):
        return FormStep(event, draft.token, draft.question_index, draft.answers)

    async def active(self, user_id):
        async with self.repository.db.transaction() as session:
            draft = await session.get(EventFormSession, user_id)
            return draft is not None and draft.expires_at > self.repository.clock()

    async def begin(self, user_id, event_id):
        async with self.repository.db.transaction(write=True) as session:
            user = await session.scalar(
                select(TelegramUser).where(TelegramUser.id == user_id).with_for_update()
            )
            if not registration_complete(user):
                raise EventError("Complete student registration in the bot first.")
            event = await session.scalar(
                select(Event).where(Event.id == event_id).with_for_update()
            )
            if event is None or not event.registration_open:
                raise EventError("This event is not accepting registrations.")
            await discard_other_pending_events(session, user_id, event_id)
            if (
                not event.questions
                or await existing_registration(session, user, event_id) is not None
            ):
                await session.execute(
                    delete(EventFormSession).where(
                        EventFormSession.telegram_user_id == user_id,
                        EventFormSession.event_id == event_id,
                    )
                )
                if not event.questions:
                    await self.repository.enrollment.submit_answers_in_transaction(
                        session, user, event, {}, event.form_revision
                    )
                return None
            draft = await session.get(EventFormSession, user_id)
            now = self.repository.clock()
            if draft is None:
                draft = EventFormSession(telegram_user_id=user_id, event_id=event_id, answers={})
                session.add(draft)
            if (
                draft.expires_at is None
                or draft.expires_at <= now
                or draft.revision != event.form_revision
                or draft.event_id != event_id
            ):
                draft.event_id, draft.revision, draft.question_index = (
                    event_id,
                    event.form_revision,
                    0,
                )
                draft.answers, draft.token = {}, secrets.token_hex(8)
            draft.expires_at = now + FORM_SESSION_TTL
            return self._step(event, draft)

    async def resume(self, user_id):
        async with self.repository.db.transaction() as session:
            draft = await session.get(EventFormSession, user_id)
            event_id = (
                draft.event_id
                if draft is not None and draft.expires_at > self.repository.clock()
                else None
            )
        if event_id:
            return await self.begin(user_id, event_id)
        forms = await self.repository.pending_forms(user_id)
        return await self.begin(user_id, forms[0].id) if forms else None

    async def respond(self, user_id, *, text=None, token=None, action=None, option=None):
        async with self.repository.db.transaction(write=True) as session:
            user = await session.scalar(
                select(TelegramUser).where(TelegramUser.id == user_id).with_for_update()
            )
            if not registration_complete(user):
                raise EventError("Complete student registration first.")
            draft = await session.get(EventFormSession, user_id)
            now = self.repository.clock()
            if draft is None or draft.expires_at <= now:
                raise EventError(
                    "This questionnaire expired. Open the event link or send /start to restart it."
                )
            event = await session.scalar(
                select(Event).where(Event.id == draft.event_id).with_for_update()
            )
            if event is None or not event.registration_open:
                raise EventError(
                    "Registration for this event is closed. Please contact the organizer."
                )
            if draft.revision != event.form_revision:
                raise EventError("This form was updated. Send /start to reload its questions.")
            if token is not None and token != draft.token:
                raise EventError(
                    "This button belongs to an earlier question. Use the latest message or send /start."
                )
            question = event.questions[draft.question_index]
            answers, advance = apply_question_response(
                question,
                draft.answers,
                text=text,
                action=action,
                option=option,
            )
            if not advance:
                draft.answers, draft.expires_at = answers, now + FORM_SESSION_TTL
                return self._step(event, draft), None
            draft.answers = answers
            draft.question_index += 1
            if draft.question_index == len(event.questions):
                await self.repository.enrollment.submit_answers_in_transaction(
                    session, user, event, answers, draft.revision
                )
                await session.delete(draft)
                return None, event
            draft.token, draft.expires_at = secrets.token_hex(8), now + FORM_SESSION_TTL
            return self._step(event, draft), None

    async def cancel(self, user_id):
        async with self.repository.db.transaction(write=True) as session:
            await session.scalar(
                select(TelegramUser).where(TelegramUser.id == user_id).with_for_update()
            )
            draft = await session.get(EventFormSession, user_id)
            if draft is None:
                return False
            await session.execute(
                delete(PendingEventRegistration).where(
                    PendingEventRegistration.telegram_user_id == user_id,
                    PendingEventRegistration.event_id == draft.event_id,
                )
            )
            await session.delete(draft)
            return True
