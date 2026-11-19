"""Password plus a browser-bound, one-use Telegram code. Secrets are hashed at rest."""

import asyncio
import hashlib
import hmac
import re
import secrets
from datetime import timedelta
from uuid import uuid4

from aiogram.utils.formatting import Code, Text
from sqlalchemy import delete, func, select

from app.analytics.models import AdminChallenge, AdminLoginAttempt, AdminSession, AnalyticsSetting
from app.clock import utc_now


class LoginError(Exception):
    def __init__(self, message="Sign-in failed", status=401):
        super().__init__(message)
        self.status = status


def hash_password(password, *, salt=None):
    if not isinstance(password, str) or not 12 <= len(password) <= 128:
        raise ValueError("Use a password between 12 and 128 characters")
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=2**17, r=8, p=1, maxmem=256 * 1024 * 1024
    )
    return f"scrypt$131072$8$1${salt.hex()}${digest.hex()}"


def valid_password_hash(value):
    return (
        isinstance(value, str)
        and re.fullmatch(r"scrypt\$131072\$8\$1\$[0-9a-f]{32}\$[0-9a-f]{128}", value) is not None
    )


def check_password(password, encoded):
    if (
        not valid_password_hash(encoded)
        or not isinstance(password, str)
        or not 12 <= len(password) <= 128
    ):
        return False
    salt = bytes.fromhex(encoded.split("$")[4])
    # No tunable parameters from HTTP input or an untrusted hash.
    return hmac.compare_digest(hash_password(password, salt=salt), encoded)


def normalize_code(code):
    # Clipboard text can include whitespace or invisible bidirectional markers.
    # Keep all other characters, so malformed or additional digits still fail.
    return re.sub(r"[\s\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]", "", code)


class AdminAuth:
    def __init__(self, database, bot, *, admin_ids, password_hash, secret, clock=utc_now):
        self.db, self.bot, self.clock = database, bot, clock
        self.admin_ids = frozenset(admin_ids)
        self.password_hash, self.secret = password_hash, secret.encode()
        self.hash_slots = asyncio.Semaphore(2)

    def digest(self, value):
        return hmac.new(self.secret, value.encode(), hashlib.sha256).hexdigest()

    def csrf(self, token):
        return self.digest("csrf:" + token)

    async def _gate(self, session):
        await session.execute(
            self.db.insert(AnalyticsSetting)
            .values(key="auth_lock", value="1")
            .on_conflict_do_nothing()
        )
        await session.scalar(
            select(AnalyticsSetting).where(AnalyticsSetting.key == "auth_lock").with_for_update()
        )

    async def request(self, administrator_id, password):
        now, attempt_id = self.clock(), str(uuid4())
        async with self.db.transaction(write=True) as session:
            await self._gate(session)
            base = (
                select(func.count())
                .select_from(AdminLoginAttempt)
                .where(AdminLoginAttempt.occurred_at > now - timedelta(minutes=15))
            )
            if (await session.scalar(base)) >= 100 or (
                await session.scalar(
                    base.where(AdminLoginAttempt.administrator_id == administrator_id)
                )
            ) >= 5:
                raise LoginError("Too many attempts, try again in 15 minutes", 429)
            session.add(
                AdminLoginAttempt(
                    id=attempt_id,
                    administrator_id=administrator_id,
                    occurred_at=now,
                    outcome="password_check",
                )
            )
        if self.hash_slots.locked():
            raise LoginError("Sign-in is busy, try again shortly", 429)
        async with self.hash_slots:
            valid = await asyncio.to_thread(check_password, password, self.password_hash)
        if not valid or administrator_id not in self.admin_ids:
            raise LoginError()
        code, browser = f"{secrets.randbelow(1000000):06d}", secrets.token_urlsafe(32)
        challenge_id = str(uuid4())
        async with self.db.transaction(write=True) as session:
            await self._gate(session)
            latest = await session.scalar(
                select(AdminChallenge.created_at)
                .where(AdminChallenge.administrator_id == administrator_id)
                .order_by(AdminChallenge.created_at.desc())
                .limit(1)
            )
            if latest and (now - latest).total_seconds() < 60:
                raise LoginError("Wait one minute before requesting another code", 429)
            await session.execute(
                delete(AdminChallenge).where(AdminChallenge.administrator_id == administrator_id)
            )
            session.add(
                AdminChallenge(
                    id=challenge_id,
                    administrator_id=administrator_id,
                    browser_hash=self.digest(browser),
                    code_hash=self.digest(f"code:{challenge_id}:{browser}:{code}"),
                    credential_hash=self.digest(self.password_hash),
                    attempts_left=5,
                    created_at=now,
                    expires_at=now + timedelta(minutes=5),
                    delivered=False,
                )
            )
        try:
            # No automatic retries: an ambiguous delivery invalidates this challenge.
            async with asyncio.timeout(10):
                await self.bot.send_message(
                    administrator_id,
                    **Text(
                        "Social Registrar · Analytics sign-in\n\n",
                        "Your one-time code: ",
                        Code(code),
                        "\n\nExpires in 5 minutes\n",
                        "Only enter this code on the analytics sign-in page\n",
                        "If you did not request it, do not share the code",
                    ).as_kwargs(),
                )
        except Exception:
            async with self.db.transaction(write=True) as session:
                await session.execute(
                    delete(AdminChallenge).where(AdminChallenge.id == challenge_id)
                )
            raise LoginError(
                "We couldn't deliver the Telegram code, try again later", 503
            ) from None
        async with self.db.transaction(write=True) as session:
            challenge = await session.get(AdminChallenge, challenge_id, with_for_update=True)
            if challenge is None:
                raise LoginError("This request was replaced, start sign-in again")
            challenge.delivered = True
        return {"challenge_id": challenge_id, "expires_in": 300}, browser

    async def verify(self, challenge_id, browser, code):
        code = normalize_code(code)
        now, token = self.clock(), secrets.token_urlsafe(32)
        error = None
        async with self.db.transaction(write=True) as session:
            challenge = await session.get(AdminChallenge, challenge_id, with_for_update=True)
            if (
                challenge is None
                or challenge.administrator_id not in self.admin_ids
                or not challenge.delivered
                or not hmac.compare_digest(
                    challenge.credential_hash, self.digest(self.password_hash)
                )
                or challenge.expires_at <= now
                or challenge.attempts_left <= 0
                or not hmac.compare_digest(challenge.browser_hash, self.digest(browser))
            ):
                error = LoginError("Code is unavailable or expired, start sign-in again")
            else:
                challenge.attempts_left -= 1
                if not re.fullmatch(r"[0-9]{6}", code) or not hmac.compare_digest(
                    challenge.code_hash, self.digest(f"code:{challenge_id}:{browser}:{code}")
                ):
                    error = LoginError("Incorrect code")
                else:
                    admin_id = challenge.administrator_id
                    await session.delete(challenge)
                    session.add(
                        AdminSession(
                            token_hash=self.digest(token),
                            administrator_id=admin_id,
                            credential_hash=self.digest(self.password_hash),
                            csrf_hash=self.digest(self.csrf(token)),
                            created_at=now,
                            last_seen_at=now,
                            expires_at=now + timedelta(hours=8),
                        )
                    )
                    session.add(
                        AdminLoginAttempt(
                            id=str(uuid4()),
                            administrator_id=admin_id,
                            occurred_at=now,
                            outcome="signed_in",
                        )
                    )
        if error:
            raise error
        return token

    async def authenticate(self, token, *, csrf=None):
        if not token or len(token) > 100:
            raise LoginError("Sign in to view analytics")
        now = self.clock()
        async with self.db.transaction(write=True) as session:
            row = await session.get(AdminSession, self.digest(token), with_for_update=True)
            if (
                row is None
                or row.administrator_id not in self.admin_ids
                or row.expires_at <= now
                or row.last_seen_at <= now - timedelta(minutes=30)
                or not hmac.compare_digest(row.credential_hash, self.digest(self.password_hash))
            ):
                raise LoginError("Your session expired, sign in again")
            if csrf is not None and not hmac.compare_digest(row.csrf_hash, self.digest(csrf)):
                raise LoginError("Refresh the page and try again", 403)
            if (now - row.last_seen_at).total_seconds() >= 60:
                row.last_seen_at = now
            return row.administrator_id

    async def logout(self, token):
        async with self.db.transaction(write=True) as session:
            await session.execute(
                delete(AdminSession).where(AdminSession.token_hash == self.digest(token))
            )
