"""Atomically leave a user's unfinished chat flows without deleting completed registrations."""

from sqlalchemy import delete, select, update

from app.analytics.events import record
from app.models import (
    Broadcast,
    BroadcastRecipient,
    EventFormSession,
    PendingEventRegistration,
    TelegramUser,
    VerificationChallenge,
)
from app.registration.history import record_registration_event
from app.registration_state import registration_complete


async def cancel_current(database, user_id, now):
    async with database.transaction(write=True) as session:
        user = await session.scalar(
            select(TelegramUser).where(TelegramUser.id == user_id).with_for_update()
        )
        if user is None:
            return
        record(session, "conversation_cancelled", at=now, user_id=user_id)
        if not registration_complete(user):
            user.verified_at = user.outlook_profile_id = None
            user.phone_number = user.phone_shared_at = None
            user.education_level = user.education_selected_at = None
        for model in (VerificationChallenge, EventFormSession, PendingEventRegistration):
            await session.execute(delete(model).where(model.telegram_user_id == user_id))
        drafts = await session.scalars(
            select(Broadcast)
            .where(Broadcast.owner_id == user_id, Broadcast.status.in_(["composing", "preview"]))
            .order_by(Broadcast.id)
            .with_for_update()
        )
        for draft in drafts:
            draft.status, draft.completed_at = "cancelled", now
            draft.prompt_message_id = draft.source_message_id = draft.original_message_id = None
            draft.revision += 1
            await session.execute(
                update(BroadcastRecipient)
                .where(
                    BroadcastRecipient.broadcast_id == draft.id,
                    BroadcastRecipient.status == "pending",
                )
                .values(status="cancelled", updated_at=now)
            )
        record_registration_event(session, user_id, "conversation_cancelled", now)
