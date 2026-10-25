"""Stable event API; persistence responsibilities live in app.events components."""

from app.clock import utc_now
from app.event_errors import EventError
from app.events.enrollment import EventEnrollment
from app.events.links import event_id_from_payload
from app.events.queries import EventQueries, MembersPage, OwnedEventsPage
from app.events.retention import EventAnswerRetention
from app.events.settings import EventSettingsRepository

__all__ = [
    "EventError",
    "EventRepository",
    "MembersPage",
    "OwnedEventsPage",
    "event_id_from_payload",
]


class EventRepository:
    """Compose event operations without exposing SQL or transaction internals to transports."""

    EVENTS_PAGE_SIZE = EventQueries.EVENTS_PAGE_SIZE
    MEMBERS_PAGE_SIZE = EventQueries.MEMBERS_PAGE_SIZE

    def __init__(self, database, *, clock=None):
        self.db = database
        self.clock = clock or utc_now
        self.enrollment = EventEnrollment(database, clock=self.clock)
        self.queries = EventQueries(database, clock=self.clock)
        self.retention = EventAnswerRetention(database, clock=self.clock)
        self.events = EventSettingsRepository(database, clock=self.clock)

    async def is_organizer(self, user_id):
        return await self.events.is_organizer(user_id)

    async def require_organizer(self, user_id):
        return await self.events.require_organizer(user_id)

    async def create(self, user_id, title="New Form"):
        return await self.events.create(user_id, title)

    async def settings(self, user_id, event_id):
        return await self.events.settings(user_id, event_id)

    async def configure(self, user_id, event_id, data):
        return await self.events.configure(user_id, event_id, data)

    async def visit(self, user_id, event_id):
        return await self.enrollment.visit(user_id, event_id)

    async def pending_titles(self, user_id, *, limit=10):
        return await self.enrollment.pending_titles(user_id, limit=limit)

    async def pending_forms(self, user_id):
        return await self.enrollment.pending_forms(user_id)

    async def submit_form(self, user_id, event_id, answers, form_revision):
        return await self.enrollment.submit_form(user_id, event_id, answers, form_revision)

    async def owned_events(self, user_id, page=0):
        return await self.queries.owned_events(user_id, page)

    async def members(self, user_id, event_id, page=0):
        return await self.queries.members(user_id, event_id, page)

    async def answer_page(self, user_id, event_id, page=0):
        return await self.queries.answer_page(user_id, event_id, page)

    async def purge_answers(self, user_id=None, event_id=None):
        return await self.retention.purge_answers(user_id, event_id)
