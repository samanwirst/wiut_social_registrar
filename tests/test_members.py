from uuid import uuid4

from aiogram.types import User
import pytest
import pytest_asyncio

from app.event_repository import EventError, EventRepository
from registrar.models import Student


async def register(repository, user_id, education_level="CIFS"):
    await repository.touch_user(User(id=user_id, is_bot=False, first_name=f"Student {user_id}"))
    student_id = f"{user_id:08}"
    person = Student(student_id, f"Student {user_id}", f"{student_id}@example.test", account=f"{student_id}@example.test")
    await repository.reserve_code(user_id, person, "001234")
    await repository.consume_code(user_id, "001234")
    await repository.save_contact(user_id, user_id, "+998901234567")
    await repository.complete_registration(user_id, education_level)


@pytest_asyncio.fixture
async def member_event(repository):
    await register(repository, 100)
    events = EventRepository(repository.db, clock=repository.clock)
    event = await events.create(100, "Welcome | **Night** <test>")
    for user_id in range(1000, 1023):
        await register(repository, user_id, "CIFS" if user_id % 2 == 0 else "Level 6")
        await events.visit(user_id, event.id)
    return events, event


@pytest.mark.asyncio
async def test_ten_members_per_page_have_stable_order_and_contact_fields(member_event):
    events, event = member_event
    pages = [await events.members(100, event.id, index) for index in range(3)]
    assert [len(page.members) for page in pages] == [10, 10, 3]
    assert all(page.total == 23 and page.pages == 3 for page in pages)
    assert [member['telegram_id'] for page in pages for member in page.members] == list(range(1000, 1023))
    assert pages[0].members[0]['student_id'] == '00001000'
    assert pages[0].members[0]['phone_number'] == '+998901234567'
    assert pages[0].members[0]['education_level'] == 'CIFS'
    assert pages[0].members[1]['education_level'] == 'Level 6'
    expected = {'student_id', 'name', 'telegram_id', 'telegram_username', 'email', 'phone_number', 'education_level'}
    assert set(pages[0].members[0]) == expected
    assert (await events.members(100, event.id, 10**8)).page == 2
    assert (await events.members(100, event.id, -1)).page == 0


@pytest.mark.asyncio
async def test_member_data_is_only_available_to_the_registered_event_creator(repository):
    await register(repository, 100)
    events = EventRepository(repository.db)
    event = await events.create(100)
    await events.visit(200, event.id)
    with pytest.raises(EventError, match='Complete registration'):
        await events.members(200, event.id)
    await register(repository, 200)
    with pytest.raises(EventError, match='Only the event organizer'):
        await events.members(200, event.id)
    with pytest.raises(EventError, match='Only the event organizer'):
        await events.members(100, str(uuid4()))


@pytest.mark.asyncio
async def test_event_selector_only_lists_owned_events_and_supports_pagination(repository):
    await register(repository, 100)
    await register(repository, 200)
    events = EventRepository(repository.db)
    for index in range(7):
        await events.create(100, f'Event {index}')
    other = await events.create(200, 'Other organizer event')
    first = await events.owned_events(100)
    second = await events.owned_events(100, 1)
    assert first.total == second.total == 7 and first.pages == 2
    assert len(first.events) == 5 and len(second.events) == 2
    assert other.id not in {event.id for event in first.events + second.events}
    assert (await events.owned_events(100, 100)).page == 1


@pytest.mark.asyncio
async def test_empty_event_and_organizer_pages(repository):
    await register(repository, 100)
    events = EventRepository(repository.db)
    empty = await events.create(100)
    page = await events.members(100, empty.id)
    assert page.total == 0 and page.page == 0 and page.pages == 1 and page.members == []
    await register(repository, 200)
    owned = await events.owned_events(200)
    assert owned.events == [] and owned.total == 0 and owned.pages == 1
