from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import func, select

from app.clock import utc_now
from app.event_errors import EventError
from app.events.access import owned_event, require_registered
from app.events.selection import member_condition, selected_member_ids
from app.media_answers import MEDIA_QUESTIONS, public_attachment
from app.models import (
    Event,
    EventAnswers,
    EventRegistration,
    EventTableValues,
    OutlookProfile,
    TelegramUser,
)
from app.pagination import page_bounds


@dataclass(frozen=True)
class OwnedEventsPage:
    events: list[Event]
    total: int
    page: int
    pages: int
    member_counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class MembersPage:
    event: Event
    total: int
    page: int
    pages: int
    members: list[dict]
    export_scope: str = "all"
    member_ids: list[int | str] = field(default_factory=list)


class EventQueries:
    """Authorized, paginated organizer views."""

    EVENTS_PAGE_SIZE = 5
    MEMBERS_PAGE_SIZE = 10

    def __init__(self, database, *, clock=utc_now):
        self.db = database
        self.clock = clock

    async def owned_events(self, user_id, page=0) -> OwnedEventsPage:
        async with self.db.transaction() as session:
            await require_registered(session, user_id)
            condition = Event.creator_telegram_user_id == user_id
            total = await session.scalar(select(func.count()).select_from(Event).where(condition))
            bounds = page_bounds(total, page, self.EVENTS_PAGE_SIZE)
            page, pages = bounds.page, bounds.pages
            events = list(
                (
                    await session.scalars(
                        select(Event)
                        .where(condition)
                        .order_by(Event.created_at.desc(), Event.id.desc())
                        .offset(page * self.EVENTS_PAGE_SIZE)
                        .limit(self.EVENTS_PAGE_SIZE)
                    )
                ).all()
            )
            rows = await session.execute(
                select(EventRegistration.event_id, func.count())
                .where(EventRegistration.event_id.in_([event.id for event in events]))
                .group_by(EventRegistration.event_id)
            )
            return OwnedEventsPage(events, total, page, pages, dict(rows.all()))

    async def members(self, user_id, event_id, page=0) -> MembersPage:
        async with self.db.transaction(write=True) as session:
            return await self._members(session, user_id, event_id, page)

    async def _members(
        self, session, user_id, event_id, page, *, extended=False, export=False, selected=None
    ):
        event = await owned_event(
            session,
            user_id,
            event_id,
            lock=True,
            denied="Only the event organizer can view its members.",
        )
        condition = EventRegistration.event_id == event.id
        if selected is not None:
            condition &= member_condition(event, selected)
        total = await session.scalar(
            select(func.count()).select_from(EventRegistration).where(condition)
        )
        if selected is not None and total != len(selected):
            raise EventError("Choose only participants registered for this form")
        bounds = page_bounds(total, page, self.MEMBERS_PAGE_SIZE)
        page, pages = bounds.page, bounds.pages
        limit = total if export else self.MEMBERS_PAGE_SIZE
        identity_columns = (
            [EventRegistration.anonymous_id.label("response_id")]
            if event.anonymous
            else [
                OutlookProfile.student_id.label("student_id"),
                OutlookProfile.display_name.label("name"),
                TelegramUser.id.label("telegram_id"),
                TelegramUser.username.label("telegram_username"),
                OutlookProfile.email.label("email"),
                TelegramUser.phone_number.label("phone_number"),
                TelegramUser.education_level.label("education_level"),
            ]
        )
        query = select(
            *identity_columns,
            EventRegistration.id.label("registration_id"),
            EventRegistration.table_revision.label("row_revision"),
            EventRegistration.registered_at.label("registered_at"),
            EventRegistration.table_expires_at.label("editable_until"),
        ).select_from(EventRegistration)
        if not event.anonymous:
            query = query.join(
                TelegramUser, TelegramUser.id == EventRegistration.telegram_user_id
            ).join(OutlookProfile, OutlookProfile.id == EventRegistration.outlook_profile_id)
        order = (
            EventRegistration.anonymous_id if event.anonymous else EventRegistration.registered_at
        )
        rows = (
            (
                await session.execute(
                    query.where(condition)
                    .order_by(order, EventRegistration.id)
                    .offset(0 if export else page * self.MEMBERS_PAGE_SIZE)
                    .limit(limit)
                )
            )
            .mappings()
            .all()
        )
        values = [dict(row) for row in rows]
        if not extended:
            for item in values:
                for key in ("registration_id", "row_revision", "registered_at", "editable_until"):
                    item.pop(key)
        # Selection spans the whole owned form; contacts and answers stay paginated.
        identity = (
            EventRegistration.anonymous_id
            if event.anonymous
            else EventRegistration.telegram_user_id
        )
        member_ids = (
            list(
                await session.scalars(
                    select(identity)
                    .where(EventRegistration.event_id == event.id)
                    .order_by(identity)
                )
            )
            if extended and not export
            else []
        )
        return MembersPage(
            event,
            total,
            page,
            pages,
            values,
            "selected" if selected is not None else "all",
            member_ids,
        )

    async def answer_page(self, user_id, event_id, page=0, *, export=False, selected=None):
        if selected is not None:
            selected = selected_member_ids(selected)
        async with self.db.transaction(write=True) as session:
            members = await self._members(
                session, user_id, event_id, page, extended=True, export=export, selected=selected
            )
            registration_ids = (
                select(EventRegistration.id).where(EventRegistration.event_id == event_id)
                if export
                else [m["registration_id"] for m in members.members]
            )
            if export and selected is not None:
                registration_ids = registration_ids.where(member_condition(members.event, selected))
            table_rows = (
                await session.scalars(
                    select(EventTableValues).where(
                        EventTableValues.registration_id.in_(registration_ids),
                        EventTableValues.expires_at > self.clock(),
                    )
                )
            ).all()
            table_values = {row.registration_id: row.values for row in table_rows}
            rows = (
                await session.scalars(
                    select(EventAnswers).where(
                        EventAnswers.registration_id.in_(registration_ids),
                        EventAnswers.expires_at > self.clock(),
                    )
                )
            ).all()
            answers = {response.registration_id: response for response in rows}
            media_questions = {
                q["id"] for q in members.event.questions if q["type"] in MEDIA_QUESTIONS
            }
            for member in members.members:
                registration_id = member["registration_id"]
                member["organizer_values"] = table_values.get(member["registration_id"], {})
                editing_deadline = member["editable_until"] or member["registered_at"] + timedelta(
                    days=members.event.response_retention_days
                )
                member["editable_until"] = editing_deadline.isoformat()
                if not export and not members.event.anonymous:
                    member.pop("registered_at")
                    member.pop("registration_id")
                response = answers.get(registration_id)
                member["answers"] = (
                    {
                        key: public_attachment(
                            value, member.get("response_id") or registration_id, key
                        )
                        if key in media_questions
                        else value
                        for key, value in response.answers.items()
                    }
                    if response
                    else None
                )
                member["answers_expires_at"] = response.expires_at.isoformat() if response else None
                if members.event.anonymous:
                    if not member.get("response_id"):
                        raise EventError("This anonymous response is unavailable")
                    member["can_edit"] = self.clock() < editing_deadline
                    for key in (
                        "registration_id",
                        "registered_at",
                        "editable_until",
                        "answers_expires_at",
                    ):
                        member.pop(key, None)
        return members
