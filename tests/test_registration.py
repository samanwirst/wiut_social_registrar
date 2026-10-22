import asyncio
from datetime import timedelta
from pathlib import Path

import pytest
from aiogram.types import User
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text

from app.db import Database
from app.models import OutlookProfile, RegistrationEvent, TelegramUser, VerificationChallenge
from app.registration.profiles import upsert_outlook_profile
from app.repositories import RegistrationError, RegistrationRepository
from registrar.models import Student

PERSON = Student(
    "00000001",
    "First Student",
    "student@example.test",
    account="00000001@example.test",
    graph_id="student-graph-id",
    given_name="First",
    surname="Student",
)


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
    await repository.save_contact(100, 100, "998901234567")
    assert await repository.verified(100) is None
    assert await repository.awaiting_education(100)
    repository.test_clock[0] += timedelta(seconds=10)
    result = await repository.complete_registration(100, "Level 4")
    assert result.to_dict() == PERSON.to_dict()
    async with repository.db.transaction() as session:
        user = await session.get(TelegramUser, 100)
        assert user.first_name == "First" and user.username == "user_100"
        assert user.language_code == "en" and user.is_premium
        assert user.verified_at is not None and user.outlook_profile_id is not None
        assert (
            user.verified_at
            < user.phone_shared_at
            < user.registered_at
            == user.education_selected_at
        )
        assert user.education_level == "Level 4"
        assert user.phone_number == "+998901234567"
        profile = await session.get(OutlookProfile, user.outlook_profile_id)
        assert profile.graph_id == PERSON.graph_id and profile.given_name == "First"
        assert await session.get(VerificationChallenge, 100) is None
        events = list(
            (await session.scalars(select(RegistrationEvent).order_by(RegistrationEvent.id))).all()
        )
        assert [event.event_type for event in events] == [
            "verification_requested",
            "verification_email_accepted",
            "verification_succeeded",
            "phone_shared",
            "education_level_selected",
            "registration_completed",
        ]
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
    await repository.save_contact(100, 100, "+998901234567")
    await repository.complete_registration(100, "CIFS")
    repository.test_clock[0] += timedelta(days=1)
    await repository.touch_user(
        User(id=100, is_bot=False, first_name="Updated", language_code="ru")
    )
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
    results = await asyncio.gather(
        repository.reserve_code(100, PERSON, "001234"),
        repository.reserve_code(200, PERSON, "005678"),
        return_exceptions=True,
    )
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
        await repository.save_contact(100, 100, "+998901234567")
    assert await repository.verified(100) is None
    assert await repository.pending(100) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "contact_user_id,phone",
    [
        (200, "+998901234567"),
        (None, "+998901234567"),
        (100, ""),
        (100, "not-a-number"),
        (100, "+1234567890123456"),
    ],
)
async def test_invalid_or_foreign_contacts_do_not_finish_registration(
    repository, contact_user_id, phone
):
    await repository.reserve_code(100, PERSON, "001234")
    await repository.consume_code(100, "001234")
    with pytest.raises(RegistrationError):
        await repository.save_contact(100, contact_user_id, phone)
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
        await restarted.save_contact(100, 100, "+998901234567")
        await restarted.complete_registration(100, "CIFS")
        assert (await restarted.verified(100)).student_id == PERSON.student_id
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_repeated_and_concurrent_contacts_save_once_without_finishing_registration(
    repository,
):
    await repository.reserve_code(100, PERSON, "001234")
    await repository.consume_code(100, "001234")
    await asyncio.gather(
        repository.save_contact(100, 100, "+998901234567"),
        repository.save_contact(100, 100, "+998901234567"),
    )
    repository.test_clock[0] += timedelta(seconds=30)
    await repository.save_contact(100, 100, "+998909999999")
    async with repository.db.transaction() as session:
        user = await session.get(TelegramUser, 100)
        assert user.phone_number == "+998901234567"
        assert user.phone_shared_at == repository.clock() - timedelta(seconds=30)
        assert user.registered_at is None and user.education_level is None
        events = list(
            (
                await session.scalars(
                    select(RegistrationEvent).where(RegistrationEvent.event_type == "phone_shared")
                )
            ).all()
        )
        assert len(events) == 1


@pytest.mark.asyncio
async def test_cancel_phone_stage_clears_email_association_and_preserves_rate_limits(repository):
    await repository.reserve_code(100, PERSON, "001234")
    await repository.consume_code(100, "001234")
    await repository.cancel(100)
    assert not await repository.awaiting_phone(100)
    with pytest.raises(RegistrationError, match="Verify your Outlook email first"):
        await repository.save_contact(100, 100, "+998901234567")
    with pytest.raises(RegistrationError, match="wait"):
        await repository.reserve_code(100, PERSON, "005678")
    repository.test_clock[0] += timedelta(seconds=60)
    await repository.reserve_code(100, PERSON, "005678")
    await repository.consume_code(100, "005678")
    await repository.save_contact(100, 100, "+998901234567")
    await repository.complete_registration(100, "CIFS")
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
            profile_id = await upsert_outlook_profile(
                session, repository.insert, PERSON, repository.clock()
            )
            await session.execute(
                text(
                    "INSERT INTO telegram_users (id, first_name, created_at, last_seen_at, profile_updated_at, "
                    "verified_at, outlook_profile_id) VALUES (:id, :name, :now, :now, :now, :now, :profile_id)"
                ),
                {
                    "id": 100,
                    "name": "First",
                    "now": repository.clock().isoformat(),
                    "profile_id": profile_id,
                },
            )
        await db.migrate()
        await db.migrate()
        assert await repository.awaiting_phone(100)
        assert await repository.verified(100) is None
        await repository.save_contact(100, 100, "+998901234567")
        await repository.complete_registration(100, "CIFS")
        assert (await repository.verified(100)).student_id == PERSON.student_id
    finally:
        await db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("level", ["CIFS", "Level 4", "Level 5", "Level 6"])
async def test_education_level_is_required_to_finish_registration_and_is_persisted(
    repository, level
):
    with pytest.raises(RegistrationError, match="Confirm your email"):
        await repository.complete_registration(100, level)
    await repository.reserve_code(100, PERSON, "001234")
    await repository.consume_code(100, "001234")
    with pytest.raises(RegistrationError, match="share your own phone"):
        await repository.complete_registration(100, level)
    await repository.save_contact(100, 100, "+998901234567")
    assert not await repository.awaiting_phone(100)
    assert await repository.awaiting_education(100)
    assert await repository.verified(100) is None
    await repository.complete_registration(100, level)
    assert not await repository.awaiting_education(100)
    assert (await repository.verified(100)).student_id == PERSON.student_id
    async with repository.db.transaction() as session:
        user = await session.get(TelegramUser, 100)
        assert user.education_level == level
        assert user.education_selected_at == user.registered_at == repository.clock()


@pytest.mark.asyncio
@pytest.mark.parametrize("level", ["", "Level 3", "cifs", "Level 4; DROP TABLE telegram_users"])
async def test_invalid_education_levels_cannot_finish_registration(repository, level):
    await repository.reserve_code(100, PERSON, "001234")
    await repository.consume_code(100, "001234")
    await repository.save_contact(100, 100, "+998901234567")
    with pytest.raises(RegistrationError, match="Choose CIFS"):
        await repository.complete_registration(100, level)
    assert await repository.awaiting_education(100)
    assert await repository.verified(100) is None


@pytest.mark.asyncio
async def test_concurrent_education_selection_finishes_once_and_cannot_overwrite_level(repository):
    await repository.reserve_code(100, PERSON, "001234")
    await repository.consume_code(100, "001234")
    await repository.save_contact(100, 100, "+998901234567")
    results = await asyncio.gather(
        repository.complete_registration(100, "CIFS"),
        repository.complete_registration(100, "Level 6"),
        return_exceptions=True,
    )
    assert sum(isinstance(result, Student) for result in results) == 1
    assert sum(isinstance(result, RegistrationError) for result in results) == 1
    async with repository.db.transaction() as session:
        user = await session.get(TelegramUser, 100)
        level, timestamp = user.education_level, user.education_selected_at
        events = list(
            (
                await session.scalars(
                    select(RegistrationEvent).where(
                        RegistrationEvent.event_type == "registration_completed"
                    )
                )
            ).all()
        )
        assert len(events) == 1
    repository.test_clock[0] += timedelta(days=1)
    with pytest.raises(RegistrationError, match="already registered"):
        await repository.complete_registration(100, "Level 5")
    async with repository.db.transaction() as session:
        user = await session.get(TelegramUser, 100)
        assert user.education_level == level and user.education_selected_at == timestamp


@pytest.mark.asyncio
async def test_education_stage_survives_restart_and_cancel_clears_the_pending_identity(repository):
    await repository.reserve_code(100, PERSON, "001234")
    await repository.consume_code(100, "001234")
    await repository.save_contact(100, 100, "+998901234567")
    await repository.db.close()
    reopened = Database(repository.db.engine.url.render_as_string(hide_password=False))
    try:
        restarted = RegistrationRepository(reopened, "ab" * 32, clock=repository.clock)
        await reopened.migrate()
        assert await restarted.awaiting_education(100)
        await restarted.cancel(100)
        assert not await restarted.awaiting_education(100)
        with pytest.raises(RegistrationError, match="Confirm your email"):
            await restarted.complete_registration(100, "CIFS")
        async with reopened.transaction() as session:
            user = await session.get(TelegramUser, 100)
            assert user.phone_number is None and user.phone_shared_at is None
            assert user.verified_at is None and user.outlook_profile_id is None
            assert user.education_level is None and user.education_selected_at is None
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_existing_registered_user_migrates_to_education_step_without_losing_registration(
    tmp_path,
):
    db = Database("sqlite+aiosqlite:///" + str(tmp_path / "legacy-education.sqlite3"))
    repository = RegistrationRepository(db, "ab" * 32)
    try:

        def legacy_schema(connection):
            config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
            config.attributes["connection"] = connection
            command.upgrade(config, "0003_events")

        async with db.engine.begin() as connection:
            await connection.run_sync(legacy_schema)
        now = repository.clock() - timedelta(days=1)
        async with db.transaction(write=True) as session:
            profile_id = await upsert_outlook_profile(
                session, repository.insert, PERSON, repository.clock()
            )
            await session.execute(
                text(
                    "INSERT INTO telegram_users (id, first_name, created_at, last_seen_at, profile_updated_at, "
                    "verified_at, outlook_profile_id, phone_number, phone_shared_at, registered_at) "
                    "VALUES (100, 'First', :now, :now, :now, :now, :profile, '+998901234567', :now, :now)"
                ),
                {"now": now.isoformat(), "profile": profile_id},
            )
            repository._event(session, 100, "registration_completed", profile_id)
        await db.migrate()
        await db.migrate()
        assert await repository.awaiting_education(100)
        assert await repository.verified(100) is None
        assert await repository.pending(100) is None
        await repository.complete_registration(100, "Level 6")
        async with db.transaction() as session:
            user = await session.get(TelegramUser, 100)
            assert user.registered_at == now and user.phone_shared_at == now
            assert user.education_level == "Level 6" and user.education_selected_at > now
            events = list(
                (
                    await session.scalars(
                        select(RegistrationEvent).where(
                            RegistrationEvent.event_type == "registration_completed"
                        )
                    )
                ).all()
            )
            assert len(events) == 1
    finally:
        await db.close()
