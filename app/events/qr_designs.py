"""Owned event artwork: atomically replace both checked PNGs, never partial designs."""

from sqlalchemy import delete, select

from app.clock import utc_now
from app.events.access import owned_event
from app.models import EventQrDesign


class EventQrDesigns:
    def __init__(self, database, *, clock=utc_now):
        self.db, self.clock = database, clock

    async def selected(self, owner, event_id):
        async with self.db.transaction() as session:
            await owned_event(session, owner, event_id)
            return await session.scalar(
                select(EventQrDesign.design_id).where(EventQrDesign.event_id == event_id)
            )

    async def image(self, owner, event_id, design_id, *, transparent):
        column = EventQrDesign.transparent_png if transparent else EventQrDesign.opaque_png
        async with self.db.transaction() as session:
            await owned_event(session, owner, event_id)
            return await session.scalar(
                select(column).where(
                    EventQrDesign.event_id == event_id, EventQrDesign.design_id == design_id
                )
            )

    async def save(self, owner, event_id, design_id, images):
        if set(images) != {True, False} or not all(images.values()):
            raise ValueError("Both checked QR backgrounds are required")
        async with self.db.transaction(write=True) as session:
            await owned_event(session, owner, event_id, lock=True)
            values = dict(
                event_id=event_id,
                design_id=design_id,
                transparent_png=images[True],
                opaque_png=images[False],
                created_at=self.clock(),
            )
            await session.execute(
                self.db.insert(EventQrDesign)
                .values(**values)
                .on_conflict_do_update(index_elements=["event_id"], set_=values)
            )

    async def clear(self, owner, event_id):
        async with self.db.transaction(write=True) as session:
            await owned_event(session, owner, event_id, lock=True)
            await session.execute(delete(EventQrDesign).where(EventQrDesign.event_id == event_id))
