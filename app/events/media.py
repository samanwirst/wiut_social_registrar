"""Read submitted attachments only for their form's authenticated organizer."""

from sqlalchemy import select

from app.event_errors import EventError
from app.events.access import owned_event
from app.media_answers import MEDIA_QUESTIONS, attachment_reference
from app.models import EventAnswers, EventRegistration, OutlookProfile


async def submitted_attachment(database, owner, payload, now):
    identity, question_id = attachment_reference(payload)
    async with database.transaction() as session:
        registration = await session.scalar(
            select(EventRegistration).where(EventRegistration.id == identity)
        )
        if registration is None:
            raise EventError("This attachment is no longer available")
        event = await owned_event(session, owner, registration.event_id)
        question = next((q for q in event.questions if q["id"] == question_id), None)
        response = await session.scalar(
            select(EventAnswers).where(
                EventAnswers.registration_id == registration.id,
                EventAnswers.expires_at > now,
            )
        )
        if (
            question is None
            or question["type"] not in MEDIA_QUESTIONS
            or response is None
            or question_id not in response.answers
        ):
            raise EventError("This attachment is no longer available")
        profile = await session.get(OutlookProfile, registration.outlook_profile_id)
        return (
            event.title,
            question["label"],
            profile.student_id if profile else None,
            dict(response.answers[question_id]),
        )
