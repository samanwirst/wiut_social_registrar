import hashlib
import math
import re
import secrets
from datetime import timedelta

from sqlalchemy import delete, func, select

from app.clock import utc_now
from app.models import OutlookProfile, RegistrationEvent, TelegramUser, VerificationChallenge
from registrar.models import Student

from .errors import RegistrationError
from .history import record_registration_event
from .policy import VerificationPolicy
from .profiles import upsert_outlook_profile


class VerificationRepository:
    """Reserve, deliver, and consume challenges with transactional rate limits."""

    def __init__(self, database, secret, *, clock=utc_now):
        self.db = database
        self.clock = clock
        self.policy = VerificationPolicy(secret)

    async def pending(self, user_id) -> Student | None:
        async with self.db.transaction() as session:
            profile = await session.scalar(
                select(OutlookProfile)
                .join(
                    VerificationChallenge,
                    VerificationChallenge.outlook_profile_id == OutlookProfile.id,
                )
                .where(VerificationChallenge.telegram_user_id == user_id)
            )
            return profile.student() if profile else None

    async def reserve_code(self, user_id, student: Student, code: str) -> str:
        now = self.clock()
        nonce = secrets.token_hex(16)
        async with self.db.transaction(write=True) as session:
            user = await session.scalar(
                select(TelegramUser).where(TelegramUser.id == user_id).with_for_update()
            )
            if user is None:
                raise RegistrationError("Send /start to begin registration.")
            if user.registered_at is not None:
                raise RegistrationError(
                    "Your account is already registered. Use /start to see your profile."
                )
            if user.verified_at is not None:
                raise RegistrationError(
                    "Your email is already verified. Use /start to continue registration."
                )
            if self.db.engine.dialect.name == "postgresql":
                # Serialize requests for the same mailbox, including directory aliases.
                key = int.from_bytes(
                    hashlib.sha256(student.email.casefold().encode()).digest()[:8], signed=True
                )
                await session.execute(select(func.pg_advisory_xact_lock(key)))
            base = select(RegistrationEvent).where(
                RegistrationEvent.event_type == "verification_requested",
                RegistrationEvent.occurred_at > now - timedelta(hours=1),
            )
            own = list(
                (
                    await session.scalars(base.where(RegistrationEvent.telegram_user_id == user_id))
                ).all()
            )
            mailbox = list(
                (
                    await session.scalars(
                        base.join(OutlookProfile).where(
                            func.lower(OutlookProfile.email) == student.email.casefold()
                        )
                    )
                ).all()
            )
            recent = own + mailbox
            if recent:
                wait = (
                    self.policy.RESEND_SECONDS
                    - (now - max(item.occurred_at for item in recent)).total_seconds()
                )
                if wait > 0:
                    raise RegistrationError(
                        f"Please wait {math.ceil(wait)} seconds before requesting another code."
                    )
            if (
                len(own) >= self.policy.MAX_EMAILS_PER_HOUR
                or len(mailbox) >= self.policy.MAX_EMAILS_PER_HOUR
            ):
                raise RegistrationError("Too many code requests. Please try again in an hour.")
            profile_id = await upsert_outlook_profile(
                session, self.db.insert, student, self.clock()
            )
            await session.execute(
                delete(VerificationChallenge).where(
                    VerificationChallenge.telegram_user_id == user_id
                )
            )
            session.add(
                VerificationChallenge(
                    telegram_user_id=user_id,
                    outlook_profile_id=profile_id,
                    nonce=nonce,
                    code_hash=self.policy.digest(user_id, nonce, code),
                    attempts_left=self.policy.MAX_ATTEMPTS,
                    created_at=now,
                    expires_at=now + timedelta(seconds=self.policy.CODE_TTL_SECONDS),
                    email_status="pending",
                )
            )
            record_registration_event(
                session, user_id, "verification_requested", self.clock(), profile_id
            )
        return nonce

    async def mark_email(self, user_id, nonce, status):
        async with self.db.transaction(write=True) as session:
            challenge = await session.get(VerificationChallenge, user_id, with_for_update=True)
            if challenge is not None and challenge.nonce == nonce:
                challenge.email_status = status
                if status == "failed":
                    challenge.code_hash = ""
                    challenge.attempts_left = 0
                record_registration_event(
                    session,
                    user_id,
                    "verification_email_" + status,
                    self.clock(),
                    challenge.outlook_profile_id,
                )

    async def consume_code(self, user_id, code: str) -> Student:
        if not re.fullmatch(r"[0-9]{6}", code):
            raise RegistrationError(
                "Enter the 6-digit code from Outlook, or use /cancel to change your student ID."
            )
        error = None
        student = None
        async with self.db.transaction(write=True) as session:
            user = await session.scalar(
                select(TelegramUser).where(TelegramUser.id == user_id).with_for_update()
            )
            challenge = await session.get(VerificationChallenge, user_id, with_for_update=True)
            if user is None or challenge is None:
                error = "No verification is pending. Send your student ID first."
            elif challenge.email_status == "failed":
                error = "The email could not be submitted. Use /resend to request a new code."
            elif self.clock() >= challenge.expires_at:
                error = "Your code has expired. Use /resend to request a new code."
                record_registration_event(
                    session,
                    user_id,
                    "verification_failed",
                    self.clock(),
                    challenge.outlook_profile_id,
                    reason="expired",
                )
            elif challenge.attempts_left <= 0:
                error = "Too many incorrect attempts. Use /resend to request a new code."
            elif not self.policy.matches(challenge.code_hash, user_id, challenge.nonce, code):
                challenge.attempts_left -= 1
                record_registration_event(
                    session,
                    user_id,
                    "verification_failed",
                    self.clock(),
                    challenge.outlook_profile_id,
                    reason="incorrect_code",
                    attempts_left=challenge.attempts_left,
                )
                error = (
                    f"Incorrect code. Attempts left: {challenge.attempts_left}."
                    if challenge.attempts_left
                    else "Too many incorrect attempts. Use /resend to request a new code."
                )
            else:
                profile = await session.get(OutlookProfile, challenge.outlook_profile_id)
                user.outlook_profile_id = profile.id
                user.verified_at = self.clock()
                student = profile.student()
                record_registration_event(
                    session, user_id, "verification_succeeded", self.clock(), profile.id
                )
                await session.delete(challenge)
        if error:
            raise RegistrationError(error)
        return student
