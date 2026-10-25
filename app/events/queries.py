from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import func, select

from app.clock import utc_now
from app.events.access import owned_event, require_registered
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
        async with self.db.transaction() as session:
            return await self._members(session, user_id, event_id, page)

    async def _members(self, session, user_id, event_id, page, *, extended=False):
        event = await owned_event(
            session, user_id, event_id, denied="Only the event organizer can view its members."
        )
        total = await session.scalar(
            select(func.count())
            .select_from(EventRegistration)
            .where(EventRegistration.event_id == event.id)
        )
        bounds = page_bounds(total, page, self.MEMBERS_PAGE_SIZE)
        page, pages = bounds.page, bounds.pages
        rows = (
            (
                await session.execute(
                    select(
                        OutlookProfile.student_id.label("student_id"),
                        OutlookProfile.display_name.label("name"),
                        TelegramUser.id.label("telegram_id"),
                        TelegramUser.username.label("telegram_username"),
                        OutlookProfile.email.label("email"),
                        TelegramUser.phone_number.label("phone_number"),
                        TelegramUser.education_level.label("education_level"),
                        EventRegistration.id.label("registration_id"),
                        EventRegistration.table_revision.label("row_revision"),
                        EventRegistration.registered_at.label("registered_at"),
                        EventRegistration.table_expires_at.label("editable_until"),
                    )
                    .select_from(EventRegistration)
                    .join(TelegramUser, TelegramUser.id == EventRegistration.telegram_user_id)
                    .join(
                        OutlookProfile,
                        OutlookProfile.id == EventRegistration.outlook_profile_id,
                    )
                    .where(EventRegistration.event_id == event.id)
                    .order_by(EventRegistration.registered_at, EventRegistration.id)
                    .offset(page * self.MEMBERS_PAGE_SIZE)
                    .limit(self.MEMBERS_PAGE_SIZE)
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
        return MembersPage(event, total, page, pages, values)

    async def answer_page(self, user_id, event_id, page=0):
        async with self.db.transaction() as session:
            members = await self._members(session, user_id, event_id, page, extended=True)
            table_rows = (
                await session.scalars(
                    select(EventTableValues).where(
                        EventTableValues.registration_id.in_(
                            [m["registration_id"] for m in members.members]
                        ),
                        EventTableValues.expires_at > self.clock(),
                    )
                )
            ).all()
            table_values = {row.registration_id: row.values for row in table_rows}
            rows = (
                await session.execute(
                    select(EventRegistration.telegram_user_id, EventAnswers)
                    .join(EventAnswers, EventAnswers.registration_id == EventRegistration.id)
                    .where(
                        EventRegistration.event_id == event_id,
                        EventRegistration.telegram_user_id.in_(
                            [item["telegram_id"] for item in members.members]
                        ),
                        EventAnswers.expires_at > self.clock(),
                    )
                )
            ).all()
            answers = {user_id: response for user_id, response in rows}
            for member in members.members:
                member["organizer_values"] = table_values.get(member["registration_id"], {})
                member["editable_until"] = (
                    member["editable_until"]
                    or member["registered_at"]
                    + timedelta(days=members.event.response_retention_days)
                ).isoformat()
                member.pop("registered_at")
                member.pop("registration_id")
                response = answers.get(member["telegram_id"])
                member["answers"] = response.answers if response else None
                member["answers_expires_at"] = response.expires_at.isoformat() if response else None
        return members
