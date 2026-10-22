from dataclasses import dataclass, field

from sqlalchemy import func, select

from app.clock import utc_now
from app.events.access import owned_event, require_registered
from app.models import Event, EventAnswers, EventRegistration, OutlookProfile, TelegramUser
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

    async def _members(self, session, user_id, event_id, page):
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
        return MembersPage(event, total, page, pages, [dict(row) for row in rows])

    async def answer_page(self, user_id, event_id, page=0):
        async with self.db.transaction() as session:
            members = await self._members(session, user_id, event_id, page)
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
                response = answers.get(member["telegram_id"])
                member["answers"] = response.answers if response else None
                member["answers_expires_at"] = response.expires_at.isoformat() if response else None
        return members
