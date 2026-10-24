import re

from sqlalchemy import delete, select

from app.clock import utc_now
from app.db import Database
from app.education import EDUCATION_LEVELS
from app.events.enrollment import enroll_pending_events
from app.models import OutlookProfile, PendingEventRegistration, TelegramUser, VerificationChallenge
from app.registration.errors import RegistrationError
from app.registration.history import record_registration_event
from app.registration.policy import VerificationPolicy
from app.registration.profiles import upsert_outlook_profile
from app.registration.verification import VerificationRepository
from app.registration_state import email_verified, missing_profile_field, registration_complete
from registrar.models import Student

__all__ = ["RegistrationError", "RegistrationRepository"]


class RegistrationRepository:
    """Student registration lifecycle; verification challenges have their own repository."""

    CODE_TTL_SECONDS = VerificationPolicy.CODE_TTL_SECONDS
    RESEND_SECONDS = VerificationPolicy.RESEND_SECONDS
    MAX_ATTEMPTS = VerificationPolicy.MAX_ATTEMPTS
    MAX_EMAILS_PER_HOUR = VerificationPolicy.MAX_EMAILS_PER_HOUR

    def __init__(self, database: Database, secret: str, *, clock=None):
        self.db = database
        self.clock = clock or utc_now
        self.insert = database.insert
        self.verification = VerificationRepository(database, secret, clock=self.clock)

    def _event(self, session, user_id, name, profile_id=None, **details):
        record_registration_event(session, user_id, name, self.clock(), profile_id, **details)

    async def pending(self, user_id):
        return await self.verification.pending(user_id)

    async def email_status(self, user_id):
        return await self.verification.email_status(user_id)

    async def reserve_code(self, user_id, student, code):
        return await self.verification.reserve_code(user_id, student, code)

    async def mark_email(self, user_id, nonce, status):
        return await self.verification.mark_email(user_id, nonce, status)

    async def consume_code(self, user_id, code):
        return await self.verification.consume_code(user_id, code)

    async def touch_user(self, telegram_user):
        now = self.clock()
        data = {
            key: getattr(telegram_user, key)
            for key in ("first_name", "last_name", "username", "language_code", "is_premium")
        }
        async with self.db.transaction(write=True) as session:
            existing = await session.get(TelegramUser, telegram_user.id)
            changed = existing is None or any(
                getattr(existing, key) != value for key, value in data.items()
            )
            stmt = self.insert(TelegramUser).values(
                id=telegram_user.id,
                **data,
                created_at=now,
                last_seen_at=now,
                profile_updated_at=now,
            )
            updates = {**data, "last_seen_at": now}
            if changed:
                updates["profile_updated_at"] = now
            await session.execute(
                stmt.on_conflict_do_update(index_elements=[TelegramUser.id], set_=updates)
            )

    async def verified(self, user_id) -> Student | None:
        async with self.db.transaction() as session:
            row = (
                await session.execute(
                    select(TelegramUser, OutlookProfile)
                    .join(OutlookProfile, TelegramUser.outlook_profile_id == OutlookProfile.id)
                    .where(TelegramUser.id == user_id)
                )
            ).first()
            return row[1].student() if row is not None and registration_complete(row[0]) else None

    async def education_level(self, user_id) -> str | None:
        async with self.db.transaction() as session:
            user = await session.get(TelegramUser, user_id)
            return user.education_level if registration_complete(user) else None

    async def next_profile_field(self, user_id) -> str | None:
        async with self.db.transaction() as session:
            return missing_profile_field(await session.get(TelegramUser, user_id))

    async def awaiting_phone(self, user_id) -> bool:
        return await self.next_profile_field(user_id) == "phone"

    async def awaiting_education(self, user_id) -> bool:
        return await self.next_profile_field(user_id) == "education"

    async def save_contact(self, user_id, contact_user_id, phone_number: str) -> None:
        if contact_user_id != user_id:
            raise RegistrationError("Share your own Telegram contact using the button below.")
        phone_number = phone_number.strip()
        if not re.fullmatch(r"\+?[1-9][0-9]{1,14}", phone_number):
            raise RegistrationError(
                "The contact has an invalid phone number. Please use the Share phone number button."
            )
        phone_number = "+" + phone_number.lstrip("+")
        async with self.db.transaction(write=True) as session:
            user = await session.scalar(
                select(TelegramUser).where(TelegramUser.id == user_id).with_for_update()
            )
            if not email_verified(user):
                raise RegistrationError(
                    "Verify your Outlook email first. Send /start to begin registration."
                )
            if user.phone_number is None:
                now = self.clock()
                user.phone_number = phone_number
                user.phone_shared_at = now
                self._event(session, user_id, "phone_shared", user.outlook_profile_id)

    async def complete_registration(self, user_id, education_level: str) -> Student:
        if education_level not in EDUCATION_LEVELS.values():
            raise RegistrationError("Choose CIFS, Level 4, Level 5, or Level 6 using the buttons.")
        async with self.db.transaction(write=True) as session:
            user = await session.scalar(
                select(TelegramUser).where(TelegramUser.id == user_id).with_for_update()
            )
            if not email_verified(user) or user.phone_number is None:
                raise RegistrationError(
                    "Confirm your email and share your own phone number first. Use /start to continue."
                )
            if user.education_level is not None:
                raise RegistrationError(
                    "Your account is already registered. Use /me to view your own profile."
                )
            profile = await session.get(OutlookProfile, user.outlook_profile_id)
            now = self.clock()
            user.education_level = education_level
            user.education_selected_at = now
            self._event(
                session,
                user_id,
                "education_level_selected",
                profile.id,
                education_level=education_level,
            )
            if user.registered_at is None:
                user.registered_at = now
                self._event(session, user_id, "registration_completed", profile.id)
            await enroll_pending_events(session, self.insert, user, now)
            return profile.student()

    async def cancel(self, user_id):
        async with self.db.transaction(write=True) as session:
            user = await session.scalar(
                select(TelegramUser).where(TelegramUser.id == user_id).with_for_update()
            )
            if user is not None:
                if user.registered_at is not None:
                    raise RegistrationError(
                        "Your account is already registered. Use /me to view your own profile."
                    )
                user.verified_at = None
                user.outlook_profile_id = None
                user.phone_number = None
                user.phone_shared_at = None
                user.education_level = None
                user.education_selected_at = None
            await session.execute(
                delete(VerificationChallenge).where(
                    VerificationChallenge.telegram_user_id == user_id
                )
            )
            await session.execute(
                delete(PendingEventRegistration).where(
                    PendingEventRegistration.telegram_user_id == user_id
                )
            )
            self._event(session, user_id, "registration_cancelled")

    async def event(self, user_id, name, student=None, **details):
        async with self.db.transaction(write=True) as session:
            profile_id = (
                await upsert_outlook_profile(session, self.insert, student, self.clock())
                if student
                else None
            )
            self._event(session, user_id, name, profile_id, **details)
