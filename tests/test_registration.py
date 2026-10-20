import asyncio
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path

from aiogram.types import User
from alembic import command
from alembic.config import Config
import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.engine import make_url

from app.db import Database
from app.models import OutlookProfile, RegistrationEvent, TelegramUser, VerificationChallenge
from app.repositories import RegistrationError, RegistrationRepository
from registrar.models import Student

PERSON = Student("00000001", "First Student", "student@example.test", account="00000001@example.test",
                 graph_id="student-graph-id", given_name="First", surname="Student")


@pytest_asyncio.fixture(params=["sqlite"] + (["postgresql"] if os.environ.get("TEST_DATABASE_URL") else []))
async def repository(request, tmp_path):
    url = os.environ["TEST_DATABASE_URL"] if request.param == "postgresql" else "sqlite+aiosqlite:///" + str(tmp_path / "db.sqlite3")
    if request.param == "postgresql":
        assert make_url(url).database.endswith("_test"), "Use a dedicated database ending in _test."
    db = Database(url)
    await db.migrate()
    if request.param == "postgresql":
        async with db.engine.begin() as connection:
            await connection.execute(text("TRUNCATE registration_events, verification_challenges, telegram_users, outlook_profiles RESTART IDENTITY CASCADE"))
    now = [datetime(2026, 10, 21, tzinfo=timezone.utc)]
    repo = RegistrationRepository(db, "ab" * 32, clock=lambda: now[0])
    repo.test_clock = now
    for user_id in (100, 200):
        await repo.touch_user(User(id=user_id, is_bot=False, first_name="First", last_name="Last",
                                   username=f"user_{user_id}", language_code="en", is_premium=True))
    try:
        yield repo
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_complete_registration_persists_meaningful_profiles_and_events(repository):
    nonce = await repository.reserve_code(100, PERSON, "001234")
    await repository.mark_email(100, nonce, "accepted")
    assert await repository.verified(100) is None
    async with repository.db.transaction() as session:
        challenge = await session.get(VerificationChallenge, 100)
        assert challenge.code_hash != "001234" and len(challenge.code_hash) == 64
    result = await repository.consume_code(100, "001234")
    assert result.to_dict() == PERSON.to_dict()
    assert await repository.verified(100) is None
    assert await repository.awaiting_phone(100)
    async with repository.db.transaction() as session:
        user = await session.get(TelegramUser, 100)
        assert user.registered_at is None and user.phone_number is None
        assert await session.get(VerificationChallenge, 100) is None
    repository.test_clock[0] += timedelta(seconds=30)
    result = await repository.complete_registration(100, 100, "998901234567")
    assert result.to_dict() == PERSON.to_dict()
    async with repository.db.transaction() as session:
        user = await session.get(TelegramUser, 100)
        assert user.first_name == "First" and user.username == "user_100"
        assert user.language_code == "en" and user.is_premium
        assert user.verified_at is not None and user.outlook_profile_id is not None
        assert user.verified_at < user.registered_at == user.phone_shared_at
        assert user.phone_number == "+998901234567"
        profile = await session.get(OutlookProfile, user.outlook_profile_id)
        assert profile.graph_id == PERSON.graph_id and profile.given_name == "First"
        assert await session.get(VerificationChallenge, 100) is None
        events = list((await session.scalars(select(RegistrationEvent).order_by(RegistrationEvent.id))).all())
        assert [event.event_type for event in events] == ["verification_requested", "verification_email_accepted",
                                                        "verification_succeeded", "registration_completed"]
        assert "001234" not in str([event.details for event in events])
        assert "998901234567" not in str([event.details for event in events])
    await repository.db.migrate()
    assert (await repository.verified(100)).student_id == PERSON.student_id
    with pytest.raises(RegistrationError, match="No verification"):
        await repository.consume_code(100, "001234")


@pytest.mark.asyncio
async def test_profile_refresh_preserves_first_seen_and_verification(repository):
    await repository.reserve_code(100, PERSON, "001234")
    await repository.consume_code(100, "001234")
    await repository.complete_registration(100, 100, "+998901234567")
    repository.test_clock[0] += timedelta(days=1)
    await repository.touch_user(User(id=100, is_bot=False, first_name="Updated", language_code="ru"))
    async with repository.db.transaction() as session:
        user = await session.get(TelegramUser, 100)
        assert user.created_at < user.last_seen_at
        assert user.profile_updated_at == user.last_seen_at
        assert user.verified_at < user.last_seen_at
        assert user.first_name == "Updated" and user.username is None and user.language_code == "ru"
        assert user.phone_number == "+998901234567" and user.registered_at < user.last_seen_at


@pytest.mark.asyncio
async def test_codes_are_bound_to_one_telegram_user(repository):
    await repository.reserve_code(100, PERSON, "001234")
    with pytest.raises(RegistrationError):
        await repository.consume_code(200, "001234")
    assert await repository.verified(200) is None
    assert (await repository.consume_code(100, "001234")).account == PERSON.account


@pytest.mark.asyncio
async def test_expiry_is_enforced_across_database_connections(repository):
    await repository.reserve_code(100, PERSON, "001234")
    repository.test_clock[0] += timedelta(seconds=600)
    with pytest.raises(RegistrationError, match="expired"):
        await repository.consume_code(100, "001234")
    assert await repository.verified(100) is None


@pytest.mark.asyncio
async def test_attempt_limit_is_persistent_and_does_not_accept_correct_code(repository):
    await repository.reserve_code(100, PERSON, "001234")
    for _ in range(5):
        with pytest.raises(RegistrationError):
            await repository.consume_code(100, "999999")
    with pytest.raises(RegistrationError, match="Too many incorrect"):
        await repository.consume_code(100, "001234")
    async with repository.db.transaction() as session:
        assert (await session.get(VerificationChallenge, 100)).attempts_left == 0


@pytest.mark.asyncio
async def test_resend_replaces_old_code_and_uses_new_salt(repository):
    old_nonce = await repository.reserve_code(100, PERSON, "001234")
    repository.test_clock[0] += timedelta(seconds=60)
    new_nonce = await repository.reserve_code(100, PERSON, "005678")
    assert new_nonce != old_nonce
    with pytest.raises(RegistrationError):
        await repository.consume_code(100, "001234")
    assert (await repository.consume_code(100, "005678")).student_id == PERSON.student_id


@pytest.mark.asyncio
async def test_cooldown_and_hourly_limits_apply_to_user_and_mailbox(repository):
    for index in range(5):
        await repository.reserve_code(100, PERSON, "001234")
        with pytest.raises(RegistrationError, match="wait"):
            await repository.reserve_code(200, PERSON, "005678")
        repository.test_clock[0] += timedelta(seconds=60)
    with pytest.raises(RegistrationError, match="Too many code requests"):
        await repository.reserve_code(100, PERSON, "005678")
    repository.test_clock[0] += timedelta(hours=1)
    await repository.reserve_code(200, PERSON, "005678")


@pytest.mark.asyncio
async def test_concurrent_recipient_requests_reserve_only_one_code(repository):
    results = await asyncio.gather(repository.reserve_code(100, PERSON, "001234"),
                                   repository.reserve_code(200, PERSON, "005678"), return_exceptions=True)
    assert sum(isinstance(result, str) for result in results) == 1
    assert sum(isinstance(result, RegistrationError) for result in results) == 1


@pytest.mark.asyncio
async def test_failed_submission_cannot_be_verified_but_unknown_submission_can(repository):
    nonce = await repository.reserve_code(100, PERSON, "001234")
    await repository.mark_email(100, nonce, "failed")
    with pytest.raises(RegistrationError, match="could not be submitted"):
        await repository.consume_code(100, "001234")
    repository.test_clock[0] += timedelta(seconds=60)
    nonce = await repository.reserve_code(100, PERSON, "005678")
    await repository.mark_email(100, nonce, "unknown")
    await repository.consume_code(100, "005678")


@pytest.mark.asyncio
async def test_phone_cannot_complete_registration_before_email_verification(repository):
    await repository.reserve_code(100, PERSON, "001234")
    with pytest.raises(RegistrationError, match="Verify your Outlook email first"):
        await repository.complete_registration(100, 100, "+998901234567")
    assert await repository.verified(100) is None
    assert await repository.pending(100) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("contact_user_id,phone", [
    (200, "+998901234567"), (None, "+998901234567"),
    (100, ""), (100, "not-a-number"), (100, "+1234567890123456"),
])
async def test_invalid_or_foreign_contacts_do_not_finish_registration(repository, contact_user_id, phone):
    await repository.reserve_code(100, PERSON, "001234")
    await repository.consume_code(100, "001234")
    with pytest.raises(RegistrationError):
        await repository.complete_registration(100, contact_user_id, phone)
    assert await repository.awaiting_phone(100)
    assert await repository.verified(100) is None
    async with repository.db.transaction() as session:
        user = await session.get(TelegramUser, 100)
        assert user.phone_number is None and user.registered_at is None


@pytest.mark.asyncio
async def test_phone_stage_survives_restart_and_does_not_require_another_code(repository):
    await repository.reserve_code(100, PERSON, "001234")
    await repository.consume_code(100, "001234")
    await repository.db.close()
    reopened = Database(repository.db.engine.url.render_as_string(hide_password=False))
    try:
        restarted = RegistrationRepository(reopened, "ab" * 32, clock=repository.clock)
        await reopened.migrate()
        assert await restarted.awaiting_phone(100)
        assert await restarted.verified(100) is None
        with pytest.raises(RegistrationError, match="email is already verified"):
            await restarted.reserve_code(100, PERSON, "005678")
        await restarted.complete_registration(100, 100, "+998901234567")
        assert (await restarted.verified(100)).student_id == PERSON.student_id
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_repeated_and_concurrent_contacts_complete_once_without_overwriting_phone(repository):
    await repository.reserve_code(100, PERSON, "001234")
    await repository.consume_code(100, "001234")
    await asyncio.gather(repository.complete_registration(100, 100, "+998901234567"),
                         repository.complete_registration(100, 100, "+998901234567"))
    repository.test_clock[0] += timedelta(seconds=30)
    await repository.complete_registration(100, 100, "+998909999999")
    async with repository.db.transaction() as session:
        user = await session.get(TelegramUser, 100)
        assert user.phone_number == "+998901234567"
        assert user.registered_at == repository.clock() - timedelta(seconds=30)
        events = list((await session.scalars(select(RegistrationEvent).where(
            RegistrationEvent.event_type == "registration_completed"))).all())
        assert len(events) == 1


@pytest.mark.asyncio
async def test_cancel_phone_stage_clears_email_association_and_preserves_rate_limits(repository):
    await repository.reserve_code(100, PERSON, "001234")
    await repository.consume_code(100, "001234")
    await repository.cancel(100)
    assert not await repository.awaiting_phone(100)
    with pytest.raises(RegistrationError, match="Verify your Outlook email first"):
        await repository.complete_registration(100, 100, "+998901234567")
    with pytest.raises(RegistrationError, match="wait"):
        await repository.reserve_code(100, PERSON, "005678")
    repository.test_clock[0] += timedelta(seconds=60)
    await repository.reserve_code(100, PERSON, "005678")
    await repository.consume_code(100, "005678")
    await repository.complete_registration(100, 100, "+998901234567")
    with pytest.raises(RegistrationError, match="already registered"):
        await repository.cancel(100)
    assert (await repository.verified(100)).student_id == PERSON.student_id


@pytest.mark.asyncio
async def test_existing_email_verified_user_migrates_to_phone_step(tmp_path):
    db = Database("sqlite+aiosqlite:///" + str(tmp_path / "legacy.sqlite3"))
    try:
        def legacy_schema(connection):
            config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
            config.attributes["connection"] = connection
            command.upgrade(config, "0001_registration")
        async with db.engine.begin() as connection:
            await connection.run_sync(legacy_schema)
        repository = RegistrationRepository(db, "ab" * 32)
        async with db.transaction(write=True) as session:
            profile_id = await repository._profile(session, PERSON)
            await session.execute(text(
                "INSERT INTO telegram_users (id, first_name, created_at, last_seen_at, profile_updated_at, "
                "verified_at, outlook_profile_id) VALUES (:id, :name, :now, :now, :now, :now, :profile_id)"
            ), {"id": 100, "name": "First", "now": repository.clock().isoformat(), "profile_id": profile_id})
        await db.migrate()
        await db.migrate()
        assert await repository.awaiting_phone(100)
        assert await repository.verified(100) is None
        await repository.complete_registration(100, 100, "+998901234567")
        assert (await repository.verified(100)).student_id == PERSON.student_id
    finally:
        await db.close()
