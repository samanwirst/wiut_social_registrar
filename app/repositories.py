from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import math
import re
import secrets

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.db import Database
from app.education import EDUCATION_LEVELS
from app.event_repository import enroll_pending_events
from app.models import OutlookProfile, PendingEventRegistration, RegistrationEvent, TelegramUser, VerificationChallenge
from registrar.models import Student


class RegistrationError(ValueError):
    """A safe message that can be shown to the registering user."""


class RegistrationRepository:
    CODE_TTL_SECONDS = 600
    RESEND_SECONDS = 60
    MAX_ATTEMPTS = 5
    MAX_EMAILS_PER_HOUR = 5

    def __init__(self, database: Database, secret: str, *, clock=None):
        self.db = database
        self._secret = bytes.fromhex(secret)
        if len(self._secret) != 32:
            raise ValueError("A 32-byte verification secret is required.")
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.insert = sqlite_insert if database.engine.dialect.name == "sqlite" else pg_insert

    def _event(self, session, user_id, name, profile_id=None, **details):
        session.add(RegistrationEvent(telegram_user_id=user_id, outlook_profile_id=profile_id,
                                     event_type=name, occurred_at=self.clock(), details=details))

    async def touch_user(self, telegram_user):
        now = self.clock()
        data = {key: getattr(telegram_user, key) for key in
                ("first_name", "last_name", "username", "language_code", "is_premium")}
        async with self.db.transaction(write=True) as session:
            existing = await session.get(TelegramUser, telegram_user.id)
            changed = existing is None or any(getattr(existing, key) != value for key, value in data.items())
            stmt = self.insert(TelegramUser).values(id=telegram_user.id, **data, created_at=now,
                                                    last_seen_at=now, profile_updated_at=now)
            updates = {**data, "last_seen_at": now}
            if changed:
                updates["profile_updated_at"] = now
            await session.execute(stmt.on_conflict_do_update(index_elements=[TelegramUser.id], set_=updates))

    async def _profile(self, session, student):
        now = self.clock()
        data = dict(student_id=student.student_id, graph_id=student.graph_id or None, account=student.account,
                    display_name=student.name or None, given_name=student.given_name or None,
                    surname=student.surname or None, email=student.email, email_addresses=student.email_addresses,
                    updated_at=now)
        stmt = self.insert(OutlookProfile).values(**data, first_seen_at=now)
        result = await session.execute(stmt.on_conflict_do_update(
            index_elements=[OutlookProfile.account], set_=data).returning(OutlookProfile.id))
        return result.scalar_one()

    async def verified(self, user_id) -> Student | None:
        async with self.db.transaction() as session:
            profile = await session.scalar(select(OutlookProfile).join(
                TelegramUser, TelegramUser.outlook_profile_id == OutlookProfile.id).where(
                    TelegramUser.id == user_id, TelegramUser.verified_at.is_not(None),
                    TelegramUser.registered_at.is_not(None), TelegramUser.phone_number.is_not(None),
                    TelegramUser.education_level.in_(EDUCATION_LEVELS.values())))
            return profile.student() if profile else None

    async def awaiting_phone(self, user_id) -> bool:
        async with self.db.transaction() as session:
            return bool(await session.scalar(select(TelegramUser.id).where(
                TelegramUser.id == user_id, TelegramUser.verified_at.is_not(None),
                TelegramUser.outlook_profile_id.is_not(None), TelegramUser.phone_number.is_(None))))

    async def awaiting_education(self, user_id) -> bool:
        async with self.db.transaction() as session:
            return bool(await session.scalar(select(TelegramUser.id).where(
                TelegramUser.id == user_id, TelegramUser.verified_at.is_not(None),
                TelegramUser.outlook_profile_id.is_not(None), TelegramUser.phone_number.is_not(None),
                TelegramUser.education_level.is_(None))))

    async def pending(self, user_id) -> Student | None:
        async with self.db.transaction() as session:
            profile = await session.scalar(select(OutlookProfile).join(
                VerificationChallenge, VerificationChallenge.outlook_profile_id == OutlookProfile.id).where(
                    VerificationChallenge.telegram_user_id == user_id))
            return profile.student() if profile else None

    def _digest(self, user_id, nonce, code):
        return hmac.new(self._secret, f"{user_id}:{nonce}:{code}".encode(), hashlib.sha256).hexdigest()

    async def reserve_code(self, user_id, student: Student, code: str) -> str:
        now = self.clock()
        nonce = secrets.token_hex(16)
        async with self.db.transaction(write=True) as session:
            user = await session.scalar(select(TelegramUser).where(TelegramUser.id == user_id).with_for_update())
            if user is None:
                raise RegistrationError("Send /start to begin registration.")
            if user.registered_at is not None:
                raise RegistrationError("Your account is already registered. Use /start to see your profile.")
            if user.verified_at is not None:
                raise RegistrationError("Your email is already verified. Use /start to continue registration.")
            if self.db.engine.dialect.name == "postgresql":
                # Serialize requests for the same mailbox, including directory aliases.
                key = int.from_bytes(hashlib.sha256(student.email.casefold().encode()).digest()[:8], signed=True)
                await session.execute(select(func.pg_advisory_xact_lock(key)))
            base = select(RegistrationEvent).where(
                RegistrationEvent.event_type == "verification_requested",
                RegistrationEvent.occurred_at > now - timedelta(hours=1))
            own = list((await session.scalars(base.where(RegistrationEvent.telegram_user_id == user_id))).all())
            mailbox = list((await session.scalars(base.join(OutlookProfile).where(
                func.lower(OutlookProfile.email) == student.email.casefold()))).all())
            recent = own + mailbox
            if recent:
                wait = self.RESEND_SECONDS - (now - max(item.occurred_at for item in recent)).total_seconds()
                if wait > 0:
                    raise RegistrationError(f"Please wait {math.ceil(wait)} seconds before requesting another code.")
            if len(own) >= self.MAX_EMAILS_PER_HOUR or len(mailbox) >= self.MAX_EMAILS_PER_HOUR:
                raise RegistrationError("Too many code requests. Please try again in an hour.")
            profile_id = await self._profile(session, student)
            await session.execute(delete(VerificationChallenge).where(VerificationChallenge.telegram_user_id == user_id))
            session.add(VerificationChallenge(telegram_user_id=user_id, outlook_profile_id=profile_id, nonce=nonce,
                        code_hash=self._digest(user_id, nonce, code), attempts_left=self.MAX_ATTEMPTS,
                        created_at=now, expires_at=now + timedelta(seconds=self.CODE_TTL_SECONDS), email_status="pending"))
            self._event(session, user_id, "verification_requested", profile_id)
        return nonce

    async def mark_email(self, user_id, nonce, status):
        async with self.db.transaction(write=True) as session:
            challenge = await session.get(VerificationChallenge, user_id, with_for_update=True)
            if challenge is not None and challenge.nonce == nonce:
                challenge.email_status = status
                if status == "failed":
                    challenge.code_hash = ""
                    challenge.attempts_left = 0
                self._event(session, user_id, "verification_email_" + status, challenge.outlook_profile_id)

    async def consume_code(self, user_id, code: str) -> Student:
        if not re.fullmatch(r"[0-9]{6}", code):
            raise RegistrationError("Enter the 6-digit code from Outlook, or use /cancel to change your student ID.")
        error = None
        student = None
        async with self.db.transaction(write=True) as session:
            user = await session.scalar(select(TelegramUser).where(TelegramUser.id == user_id).with_for_update())
            challenge = await session.get(VerificationChallenge, user_id, with_for_update=True)
            if user is None or challenge is None:
                error = "No verification is pending. Send your student ID first."
            elif challenge.email_status == "failed":
                error = "The email could not be submitted. Use /resend to request a new code."
            elif self.clock() >= challenge.expires_at:
                error = "Your code has expired. Use /resend to request a new code."
                self._event(session, user_id, "verification_failed", challenge.outlook_profile_id, reason="expired")
            elif challenge.attempts_left <= 0:
                error = "Too many incorrect attempts. Use /resend to request a new code."
            elif not hmac.compare_digest(challenge.code_hash, self._digest(user_id, challenge.nonce, code)):
                challenge.attempts_left -= 1
                self._event(session, user_id, "verification_failed", challenge.outlook_profile_id,
                            reason="incorrect_code", attempts_left=challenge.attempts_left)
                error = (f"Incorrect code. Attempts left: {challenge.attempts_left}." if challenge.attempts_left
                         else "Too many incorrect attempts. Use /resend to request a new code.")
            else:
                profile = await session.get(OutlookProfile, challenge.outlook_profile_id)
                user.outlook_profile_id = profile.id
                user.verified_at = self.clock()
                student = profile.student()
                self._event(session, user_id, "verification_succeeded", profile.id)
                await session.delete(challenge)
        if error:
            raise RegistrationError(error)
        return student

    async def save_contact(self, user_id, contact_user_id, phone_number: str) -> None:
        if contact_user_id != user_id:
            raise RegistrationError("Share your own Telegram contact using the button below.")
        phone_number = phone_number.strip()
        if not re.fullmatch(r"\+?[1-9][0-9]{1,14}", phone_number):
            raise RegistrationError("The contact has an invalid phone number. Please use the Share phone number button.")
        phone_number = "+" + phone_number.lstrip("+")
        async with self.db.transaction(write=True) as session:
            user = await session.scalar(select(TelegramUser).where(TelegramUser.id == user_id).with_for_update())
            if user is None or user.verified_at is None or user.outlook_profile_id is None:
                raise RegistrationError("Verify your Outlook email first. Send /start to begin registration.")
            if user.phone_number is None:
                now = self.clock()
                user.phone_number = phone_number
                user.phone_shared_at = now
                self._event(session, user_id, "phone_shared", user.outlook_profile_id)

    async def complete_registration(self, user_id, education_level: str) -> Student:
        if education_level not in EDUCATION_LEVELS.values():
            raise RegistrationError("Choose CIFS, Level 4, Level 5, or Level 6 using the buttons.")
        async with self.db.transaction(write=True) as session:
            user = await session.scalar(select(TelegramUser).where(TelegramUser.id == user_id).with_for_update())
            if user is None or user.verified_at is None or user.outlook_profile_id is None or user.phone_number is None:
                raise RegistrationError("Confirm your email and share your own phone number first. Use /start to continue.")
            if user.education_level is not None:
                raise RegistrationError("Your account is already registered. Use /start to see your profile.")
            profile = await session.get(OutlookProfile, user.outlook_profile_id)
            now = self.clock()
            user.education_level = education_level
            user.education_selected_at = now
            self._event(session, user_id, "education_level_selected", profile.id, education_level=education_level)
            if user.registered_at is None:
                user.registered_at = now
                self._event(session, user_id, "registration_completed", profile.id)
            await enroll_pending_events(session, self.insert, user, now)
            return profile.student()

    async def cancel(self, user_id):
        async with self.db.transaction(write=True) as session:
            user = await session.scalar(select(TelegramUser).where(TelegramUser.id == user_id).with_for_update())
            if user is not None:
                if user.registered_at is not None:
                    raise RegistrationError("Your account is already registered. Use /start to see your profile.")
                user.verified_at = None
                user.outlook_profile_id = None
                user.phone_number = None
                user.phone_shared_at = None
                user.education_level = None
                user.education_selected_at = None
            await session.execute(delete(VerificationChallenge).where(VerificationChallenge.telegram_user_id == user_id))
            await session.execute(delete(PendingEventRegistration).where(PendingEventRegistration.telegram_user_id == user_id))
            self._event(session, user_id, "registration_cancelled")

    async def event(self, user_id, name, student=None, **details):
        async with self.db.transaction(write=True) as session:
            profile_id = await self._profile(session, student) if student else None
            self._event(session, user_id, name, profile_id, **details)
