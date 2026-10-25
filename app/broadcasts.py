"""Owned audiences, Telegram preview references, and a durable delivery queue."""

from datetime import timedelta
from uuid import UUID

from sqlalchemy import delete, func, select, update

from app.clock import utc_now
from app.event_errors import EventError
from app.events.access import owned_event, require_registered
from app.models import Broadcast, BroadcastRecipient, Event, EventRegistration, TelegramUser
from app.pagination import page_bounds
from app.registration_state import registration_complete

TERMINAL = {"sent", "failed", "unknown", "cancelled"}
MAX_RECIPIENTS = 2000


class BroadcastRepository:
    def __init__(self, database, *, clock=utc_now):
        self.db, self.clock = database, clock

    async def _lock_owner(self, session, owner):
        user = await session.scalar(
            select(TelegramUser).where(TelegramUser.id == owner).with_for_update()
        )
        if not registration_complete(user):
            raise EventError("Complete student registration before preparing a message")

    async def _owned(self, session, owner, draft_id, *, lock=False):
        await require_registered(session, owner)
        query = (
            select(Broadcast)
            .join(Event, Event.id == Broadcast.event_id)
            .where(
                Broadcast.id == draft_id,
                Broadcast.owner_id == owner,
                Event.creator_telegram_user_id == owner,
            )
        )
        draft = await session.scalar(query.with_for_update(of=Broadcast) if lock else query)
        if draft is None:
            raise EventError("This message is unavailable or belongs to another organizer")
        return draft

    async def _counts(self, session, draft):
        rows = await session.execute(
            select(BroadcastRecipient.status, func.count())
            .where(BroadcastRecipient.broadcast_id == draft.id)
            .group_by(BroadcastRecipient.status)
        )
        return dict(rows.all()) or draft.counts

    async def _snapshot(self, session, draft):
        return {
            "id": draft.id,
            "event_id": draft.event_id,
            "status": draft.status,
            "revision": draft.revision,
            "total": draft.total,
            "counts": await self._counts(session, draft),
            "content_kind": draft.content_kind,
            "source_message_id": draft.source_message_id,
            "original_message_id": draft.original_message_id,
            "created_at": draft.created_at.isoformat(),
            "expires_at": draft.expires_at.isoformat(),
        }

    async def create(self, owner, event_id, recipients, request_id):
        try:
            draft_id = str(UUID(request_id))
        except (ValueError, TypeError, AttributeError):
            raise EventError("Supply a unique message request ID") from None
        if (
            not isinstance(recipients, list)
            or not 1 <= len(recipients) <= MAX_RECIPIENTS
            or any(type(v) is not int or not 0 < v < 2**63 for v in recipients)
            or len(set(recipients)) != len(recipients)
        ):
            raise EventError(f"Select 1 to {MAX_RECIPIENTS} different people")
        async with self.db.transaction(write=True) as session:
            await self._lock_owner(session, owner)
            await owned_event(session, owner, event_id, lock=True)
            existing = await session.get(Broadcast, draft_id)
            if existing is not None:
                if existing.owner_id != owner or existing.event_id != event_id:
                    raise EventError("This message request ID is already in use")
                selected = set(
                    (
                        await session.scalars(
                            select(BroadcastRecipient.telegram_user_id).where(
                                BroadcastRecipient.broadcast_id == draft_id
                            )
                        )
                    ).all()
                )
                if selected != set(recipients):
                    raise EventError("The selection changed — create a new message draft")
                return await self._snapshot(session, existing)
            valid = set(
                (
                    await session.scalars(
                        select(EventRegistration.telegram_user_id).where(
                            EventRegistration.event_id == event_id,
                            EventRegistration.telegram_user_id.in_(recipients),
                        )
                    )
                ).all()
            )
            if valid != set(recipients):
                raise EventError("Choose only people registered for your form")
            recent = await session.scalar(
                select(func.count())
                .select_from(Broadcast)
                .where(
                    Broadcast.owner_id == owner,
                    Broadcast.created_at > self.clock() - timedelta(hours=1),
                )
            )
            if recent >= 20:
                raise EventError("Too many message drafts — try again in an hour")
            draft = Broadcast(
                id=draft_id,
                event_id=event_id,
                owner_id=owner,
                status="draft",
                revision=1,
                total=len(valid),
                counts={},
                created_at=self.clock(),
                expires_at=self.clock() + timedelta(days=1),
            )
            session.add(draft)
            await session.flush()
            session.add_all(
                [
                    BroadcastRecipient(
                        broadcast_id=draft_id,
                        telegram_user_id=recipient,
                        status="pending",
                        attempts=0,
                        next_attempt_at=self.clock(),
                        updated_at=self.clock(),
                    )
                    for recipient in sorted(valid)
                ]
            )
            await session.flush()
            return await self._snapshot(session, draft)

    async def get(self, owner, draft_id):
        async with self.db.transaction() as session:
            return await self._snapshot(session, await self._owned(session, owner, draft_id))

    async def page(self, owner, event_id, page=0, *, completed_only=False):
        async with self.db.transaction() as session:
            await owned_event(session, owner, event_id)
            condition = (Broadcast.event_id == event_id, Broadcast.owner_id == owner)
            has_active = (
                await session.scalar(
                    select(Broadcast.id)
                    .where(*condition, Broadcast.status.in_(["queued", "sending"]))
                    .limit(1)
                )
                is not None
            )
            if completed_only:
                condition += (Broadcast.status == "completed",)
            total = await session.scalar(
                select(func.count()).select_from(Broadcast).where(*condition)
            )
            bounds = page_bounds(total, page, 10)
            drafts = (
                await session.scalars(
                    select(Broadcast)
                    .where(*condition)
                    .order_by(
                        Broadcast.completed_at.desc()
                        if completed_only
                        else Broadcast.created_at.desc(),
                        Broadcast.id,
                    )
                    .offset(bounds.page * 10)
                    .limit(10)
                )
            ).all()
            return {
                "broadcasts": [await self._snapshot(session, draft) for draft in drafts],
                "page": bounds.page,
                "pages": bounds.pages,
                "total": total,
                "has_active": has_active,
            }

    async def compose(self, owner, draft_id, prompt_id):
        async with self.db.transaction(write=True) as session:
            await self._lock_owner(session, owner)
            draft = await self._owned(session, owner, draft_id, lock=True)
            if draft.expires_at <= self.clock() or draft.status not in {
                "draft",
                "composing",
                "preview",
            }:
                raise EventError(
                    "This draft cannot be edited — create a new message from the table"
                )
            draft.status, draft.prompt_message_id = "composing", prompt_id
            draft.revision += 1
            return await self._snapshot(session, draft)

    async def reply_draft(self, owner, prompt_id):
        async with self.db.transaction() as session:
            draft = await session.scalar(
                select(Broadcast)
                .join(Event, Event.id == Broadcast.event_id)
                .where(
                    Broadcast.owner_id == owner,
                    Event.creator_telegram_user_id == owner,
                    Broadcast.prompt_message_id == prompt_id,
                    Broadcast.status == "composing",
                    Broadcast.expires_at > self.clock(),
                )
            )
            return await self._snapshot(session, draft) if draft is not None else None

    async def preview(
        self, owner, draft_id, prompt_id, source_id, content_kind, *, original_message_id=None
    ):
        async with self.db.transaction(write=True) as session:
            draft = await self._owned(session, owner, draft_id, lock=True)
            if (
                draft.status != "composing"
                or draft.prompt_message_id != prompt_id
                or draft.expires_at <= self.clock()
            ):
                raise EventError("This reply belongs to an older message draft")
            draft.source_message_id, draft.content_kind = source_id, content_kind
            draft.original_message_id = original_message_id
            draft.status = "preview"
            draft.revision += 1
            return await self._snapshot(session, draft)

    async def queue(self, owner, draft_id, revision):
        async with self.db.transaction(write=True) as session:
            await self._lock_owner(session, owner)
            draft = await self._owned(session, owner, draft_id, lock=True)
            if type(revision) is not int or revision != draft.revision:
                raise EventError("Use the latest message preview")
            if draft.status in {"queued", "sending", "completed"}:
                return await self._snapshot(session, draft)
            if (
                draft.status != "preview"
                or draft.source_message_id is None
                or draft.expires_at <= self.clock()
            ):
                raise EventError("Prepare and review the message before sending")
            recent = (
                await session.scalars(
                    select(Broadcast.queued_at).where(
                        Broadcast.owner_id == owner,
                        Broadcast.queued_at > self.clock() - timedelta(hours=1),
                    )
                )
            ).all()
            if len(recent) >= 10:
                raise EventError("The hourly message limit has been reached")
            if recent and (self.clock() - max(recent)).total_seconds() < 60:
                raise EventError("Wait a minute before sending another group message")
            draft.status, draft.queued_at = "queued", self.clock()
            return await self._snapshot(session, draft)

    async def cancel(self, owner, draft_id):
        async with self.db.transaction(write=True) as session:
            draft = await self._owned(session, owner, draft_id, lock=True)
            if draft.status not in {"completed", "cancelled"}:
                draft.status, draft.completed_at = "cancelled", self.clock()
                await session.execute(
                    update(BroadcastRecipient)
                    .where(
                        BroadcastRecipient.broadcast_id == draft_id,
                        BroadcastRecipient.status == "pending",
                    )
                    .values(status="cancelled", updated_at=self.clock())
                )
                draft.counts = await self._counts(session, draft)
            return await self._snapshot(session, draft)

    async def recover(self):
        # A previous process may have died after Telegram accepted a copy. Retain
        # uncertainty rather than send it again and create a duplicate broadcast.
        async with self.db.transaction(write=True) as session:
            await session.execute(
                update(BroadcastRecipient)
                .where(BroadcastRecipient.status == "sending")
                .values(status="unknown", error_code="interrupted", updated_at=self.clock())
            )

    async def claim(self):
        async with self.db.transaction(write=True) as session:
            query = (
                select(Broadcast)
                .join(BroadcastRecipient, Broadcast.id == BroadcastRecipient.broadcast_id)
                .where(
                    Broadcast.status.in_(["queued", "sending"]),
                    BroadcastRecipient.status == "pending",
                    BroadcastRecipient.next_attempt_at <= self.clock(),
                    Broadcast.expires_at > self.clock(),
                )
                .order_by(Broadcast.queued_at, BroadcastRecipient.telegram_user_id)
                .limit(1)
            )
            if self.db.engine.dialect.name == "postgresql":
                query = query.with_for_update(skip_locked=True, of=Broadcast)
            draft = await session.scalar(query)
            if draft is None:
                return None
            recipient = await session.scalar(
                select(BroadcastRecipient)
                .where(
                    BroadcastRecipient.broadcast_id == draft.id,
                    BroadcastRecipient.status == "pending",
                    BroadcastRecipient.next_attempt_at <= self.clock(),
                )
                .order_by(BroadcastRecipient.telegram_user_id)
                .limit(1)
                .with_for_update()
            )
            if recipient is None:
                return None
            draft.status = "sending"
            recipient.status = "sending"
            recipient.attempts += 1
            recipient.updated_at = self.clock()
            return {
                "broadcast_id": draft.id,
                "owner_id": draft.owner_id,
                "source_message_id": draft.source_message_id,
                "telegram_id": recipient.telegram_user_id,
                "attempts": recipient.attempts,
            }

    async def finish(self, claim, status, *, message_id=None, error_code=None, retry_after=None):
        if status not in TERMINAL | {"pending"}:
            raise ValueError("Invalid delivery outcome")
        async with self.db.transaction(write=True) as session:
            # All queue mutations lock the broadcast before a recipient. Claim uses
            # SKIP LOCKED only to find work; the single bot worker owns dispatch.
            draft = await session.get(Broadcast, claim["broadcast_id"], with_for_update=True)
            recipient = await session.get(
                BroadcastRecipient,
                (claim["broadcast_id"], claim["telegram_id"]),
                with_for_update=True,
            )
            if recipient is None or recipient.status != "sending":
                return
            if status == "pending" and (draft.status == "cancelled" or recipient.attempts >= 5):
                status = "cancelled" if draft.status == "cancelled" else "failed"
            recipient.status, recipient.message_id, recipient.error_code = (
                status,
                message_id,
                error_code,
            )
            recipient.updated_at = self.clock()
            if retry_after is not None:
                recipient.next_attempt_at = self.clock() + timedelta(seconds=max(1, retry_after))
            await session.flush()
            draft.counts = await self._counts(session, draft)
            if not any(draft.counts.get(s) for s in ["pending", "sending"]):
                if draft.status != "cancelled":
                    draft.status = "completed"
                draft.completed_at = self.clock()

    async def maintenance(self):
        async with self.db.transaction(write=True) as session:
            drafts = (
                await session.scalars(
                    select(Broadcast)
                    .where(
                        Broadcast.status.in_(["draft", "composing", "preview", "queued", "sending"])
                    )
                    .with_for_update()
                )
            ).all()
            for draft in drafts:
                await session.execute(
                    update(BroadcastRecipient)
                    .where(
                        BroadcastRecipient.broadcast_id == draft.id,
                        BroadcastRecipient.status == "sending",
                        BroadcastRecipient.updated_at <= self.clock() - timedelta(minutes=1),
                    )
                    .values(status="unknown", error_code="interrupted", updated_at=self.clock())
                )
                if draft.expires_at <= self.clock():
                    await session.execute(
                        update(BroadcastRecipient)
                        .where(
                            BroadcastRecipient.broadcast_id == draft.id,
                            BroadcastRecipient.status == "pending",
                        )
                        .values(status="cancelled", updated_at=self.clock())
                    )
                draft.counts = await self._counts(session, draft)
                if not any(draft.counts.get(s) for s in ["pending", "sending"]):
                    draft.status = "completed" if draft.queued_at is not None else "cancelled"
                    draft.completed_at = self.clock()
            old = select(Broadcast.id).where(
                Broadcast.completed_at <= self.clock() - timedelta(days=30)
            )
            await session.execute(
                delete(BroadcastRecipient).where(BroadcastRecipient.broadcast_id.in_(old))
            )
            await session.execute(
                update(Broadcast)
                .where(Broadcast.id.in_(old))
                .values(prompt_message_id=None, source_message_id=None, original_message_id=None)
            )
