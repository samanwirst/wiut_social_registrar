from aiogram import F, Router

from app.chat_formatting import error_text, recipient_count
from app.dialogs.broadcasts import open_composer, receive_message
from app.event_errors import EventError


async def composition_reply(message, broadcast_repository):
    if (
        message.chat.type != "private"
        or message.from_user is None
        or message.reply_to_message is None
    ):
        return False
    if message.text and message.text.startswith("/"):
        return False
    draft = await broadcast_repository.reply_draft(
        message.from_user.id, message.reply_to_message.message_id
    )
    return {"broadcast_draft": draft} if draft is not None else False


async def broadcast_message(message, broadcast_repository, broadcast_draft, event_repository):
    await receive_message(message, broadcast_repository, broadcast_draft, event_repository)


async def broadcast_action(callback, broadcast_repository):
    try:
        _, action, draft_id, raw_revision = callback.data.split(":")
        revision = int(raw_revision)
        if action == "send":
            draft = await broadcast_repository.queue(callback.from_user.id, draft_id, revision)
            await callback.answer("Message queued")
            await callback.message.answer(
                f"Your message is {draft['status']} for {recipient_count(draft['total'])}\nFinished messages appear at the bottom of the form's People tab"
            )
        elif action == "stop":
            await broadcast_repository.cancel(callback.from_user.id, draft_id)
            await callback.answer("Remaining deliveries stopped")
            await callback.message.answer(
                "This message was stopped\nAn already submitted delivery may still finish"
            )
        elif action == "edit":
            draft = await broadcast_repository.get(callback.from_user.id, draft_id)
            if draft["revision"] != revision or draft["status"] != "preview":
                raise EventError("Use the latest message preview")
            await callback.answer()
            # The callback's message belongs to the bot; use the authenticated user
            # explicitly rather than its from_user field when composing the reply.
            await open_composer(
                callback.message.model_copy(update={"from_user": callback.from_user}),
                broadcast_repository,
                draft_id,
                edit=True,
            )
        else:
            raise EventError("Use the latest message buttons")
    except (ValueError, EventError) as error:
        await callback.answer(
            error_text(error)
            if isinstance(error, EventError)
            else "Use the latest message buttons",
            show_alert=True,
        )


def create_router():
    router = Router(name=__name__)
    router.message.register(broadcast_message, composition_reply)
    router.callback_query.register(broadcast_action, F.data.startswith("bc:"))
    return router
