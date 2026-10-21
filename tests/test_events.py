import asyncio
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from aiogram.types import User
from sqlalchemy import select

from app.db import Database
from app.event_repository import EventError, EventRepository, event_id_from_payload
from app.models import Event, EventRegistration, PendingEventRegistration, TelegramUser
from app.repositories import RegistrationRepository
from registrar.models import Student
from tests.helpers import complete_student_registration


async def register(repository, user_id, *, student_id=None):
    student_id = student_id or f"{user_id:08}"
    student = Student(
        student_id,
        "Test Student",
        student_id + "@example.test",
        account=student_id + "@example.test",
    )
    await complete_student_registration(
        repository, user_id, student, education_level="CIFS", code="001234"
    )


@pytest.fixture
def events(repository):
    return EventRepository(repository.db, clock=repository.clock)


@pytest.mark.asyncio
async def test_event_requires_completed_registration_and_gets_unique_uuid(repository, events):
    with pytest.raises(EventError, match="Complete registration"):
        await events.create(100)
    await register(repository, 100)
    first = await events.create(100, "  Welcome   Night  ")
    second = await events.create(100)
    assert first.title == "Welcome Night" and second.title == "New Event"
    assert UUID(first.id).version == 4 and first.id != second.id
    async with repository.db.transaction() as session:
        assert (await session.get(Event, first.id)).creator_telegram_user_id == 100
        assert list(await session.scalars(select(EventRegistration))) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("title", ["", "   ", "a" * 201])
async def test_invalid_title_does_not_create_event(repository, events, title):
    await register(repository, 100)
    with pytest.raises(EventError, match="1 to 200"):
        await events.create(100, title)
    async with repository.db.transaction() as session:
        assert list(await session.scalars(select(Event))) == []


@pytest.mark.asyncio
async def test_concurrent_and_repeated_scans_preserve_one_student_registration(repository, events):
    await register(repository, 100)
    await register(repository, 200)
    event = await events.create(100, "Meetup")
    result = await asyncio.gather(events.visit(200, event.id), events.visit(200, event.id))
    assert sorted(status for _, status in result) == ["already_registered", "registered"]
    repository.test_clock[0] += timedelta(hours=1)
    assert (await events.visit(200, event.id))[1] == "already_registered"
    async with repository.db.transaction() as session:
        entry = (await session.scalars(select(EventRegistration))).one()
        user = await session.get(TelegramUser, 200)
        assert entry.event_id == event.id and entry.telegram_user_id == 200
        assert entry.outlook_profile_id == user.outlook_profile_id
        assert entry.registered_at < repository.clock()


@pytest.mark.asyncio
async def test_same_student_with_another_telegram_account_is_not_counted_twice(repository, events):
    await register(repository, 100)
    await register(repository, 200)
    event = await events.create(100)
    await events.visit(200, event.id)
    repository.test_clock[0] += timedelta(seconds=60)
    await repository.touch_user(User(id=300, is_bot=False, first_name="Same Student"))
    await register(repository, 300, student_id="00000200")
    assert (await events.visit(300, event.id))[1] == "already_registered"
    async with repository.db.transaction() as session:
        assert len(list(await session.scalars(select(EventRegistration)))) == 1


@pytest.mark.asyncio
async def test_new_student_pending_events_survive_restart_and_enroll_only_after_education(
    repository, events
):
    await register(repository, 100)
    first = await events.create(100, "First")
    second = await events.create(100, "Second")
    assert (await events.visit(200, first.id))[1] == "pending"
    await events.visit(200, first.id)
    await events.visit(200, second.id)
    assert set(await events.pending_titles(200)) == {"First", "Second"}
    await repository.reserve_code(
        200,
        Student("00000200", "Second", "200@example.test", account="00000200@example.test"),
        "001234",
    )
    await repository.consume_code(200, "001234")
    await repository.save_contact(200, 200, "+998909999999")
    async with repository.db.transaction() as session:
        assert list(await session.scalars(select(EventRegistration))) == []
        assert len(list(await session.scalars(select(PendingEventRegistration)))) == 2
    await repository.db.close()
    reopened = Database(repository.db.engine.url.render_as_string(hide_password=False))
    try:
        restarted = RegistrationRepository(reopened, "ab" * 32, clock=repository.clock)
        await reopened.migrate()
        assert await restarted.awaiting_education(200)
        await restarted.complete_registration(200, "Level 4")
        async with reopened.transaction() as session:
            entries = list(await session.scalars(select(EventRegistration)))
            assert {entry.event_id for entry in entries} == {first.id, second.id}
            assert all(entry.telegram_user_id == 200 for entry in entries)
            assert list(await session.scalars(select(PendingEventRegistration))) == []
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_event_enrollment_and_student_registration_roll_back_together(
    repository, events, monkeypatch
):
    await register(repository, 100)
    event = await events.create(100)
    await events.visit(200, event.id)
    await repository.reserve_code(
        200,
        Student("00000200", "Second", "200@example.test", account="00000200@example.test"),
        "001234",
    )
    await repository.consume_code(200, "001234")
    await repository.save_contact(200, 200, "+998909999999")
    from app import repositories

    original = repositories.enroll_pending_events

    async def fail_after_enrollment(*args):
        await original(*args)
        raise RuntimeError("Simulated transaction failure")

    monkeypatch.setattr(repositories, "enroll_pending_events", fail_after_enrollment)
    with pytest.raises(RuntimeError):
        await repository.complete_registration(200, "Level 5")
    async with repository.db.transaction() as session:
        user = await session.get(TelegramUser, 200)
        assert user.registered_at is None and user.education_level is None
        assert user.phone_number == "+998909999999"
        assert list(await session.scalars(select(EventRegistration))) == []
        assert await session.get(PendingEventRegistration, (200, event.id)) is not None
    monkeypatch.setattr(repositories, "enroll_pending_events", original)
    await repository.complete_registration(200, "Level 5")
    async with repository.db.transaction() as session:
        assert len(list(await session.scalars(select(EventRegistration)))) == 1


@pytest.mark.asyncio
async def test_cancel_discards_pending_event_registrations(repository, events):
    await register(repository, 100)
    event = await events.create(100)
    await events.visit(200, event.id)
    await repository.cancel(200)
    await register(repository, 200)
    async with repository.db.transaction() as session:
        assert list(await session.scalars(select(EventRegistration))) == []
        assert list(await session.scalars(select(PendingEventRegistration))) == []


@pytest.mark.asyncio
async def test_nonexistent_event_does_not_save_pending_registration(repository, events):
    with pytest.raises(EventError, match="does not exist"):
        await events.visit(200, str(uuid4()))
    assert await events.pending_titles(200) == []


@pytest.mark.parametrize(
    "payload",
    [
        "",
        "event_bad",
        "other_" + str(uuid4()),
        "event_" + str(UUID(int=0)),
        "event_" + uuid4().hex,
        "event_" + str(uuid4()) + "?x=1",
    ],
)
def test_invalid_event_payloads_are_rejected(payload):
    with pytest.raises(EventError, match="invalid"):
        event_id_from_payload(payload)


def test_event_payload_is_a_canonical_uuid():
    value = str(uuid4())
    assert event_id_from_payload("event_" + value) == value
    assert len("event_" + value) <= 64
