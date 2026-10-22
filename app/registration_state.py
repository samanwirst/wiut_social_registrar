"""Shared registration rules for chat, event enrollment, and panel access."""

from app.education import EDUCATION_LEVELS


def email_verified(user) -> bool:
    return user is not None and user.verified_at is not None and user.outlook_profile_id is not None


def registration_complete(user) -> bool:
    return (
        email_verified(user)
        and user.registered_at is not None
        and user.phone_number is not None
        and user.education_level in EDUCATION_LEVELS.values()
    )


def missing_profile_field(user) -> str | None:
    if not email_verified(user):
        return None
    if user.phone_number is None:
        return "phone"
    if user.education_level is None:
        return "education"
    return None
