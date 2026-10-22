from app.models import RegistrationEvent


def record_registration_event(session, user_id, name, occurred_at, profile_id=None, **details):
    session.add(
        RegistrationEvent(
            telegram_user_id=user_id,
            outlook_profile_id=profile_id,
            event_type=name,
            occurred_at=occurred_at,
            details=details,
        )
    )
