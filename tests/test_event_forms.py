import asyncio
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.event_forms import validate_answers, validate_questions
from app.event_repository import EventError, EventRepository
from app.models import EventAnswers, EventFormSession, EventRegistration, PendingEventRegistration, TelegramUser
from app.surveys import EventSurvey
from registrar.models import Student


async def registered(repository, user_id):
    person = Student(str(user_id), f"Student {user_id}", f"{user_id}@example.test", account=f"{user_id}@example.test")
    await repository.reserve_code(user_id, person, "123456")
    await repository.consume_code(user_id, "123456")
    await repository.save_contact(user_id, user_id, "+998901234567")
    await repository.complete_registration(user_id, "Level 4")


def question(kind="text", *, required=True, label="Your answer"):
    return {"id": str(uuid4()), "label": label, "type": kind, "required": required,
            "options": ["Option A", "Option B"] if kind in {"single_choice", "multiple_choice"} else []}


async def configured(repository, questions=None):
    await registered(repository, 100)
    events = EventRepository(repository.db, clock=repository.clock)
    event = await events.create(100, "Welcome")
    event = await events.configure(100, event.id, configuration(event, questions=questions or [question()]))
    return events, event


def configuration(event, **changes):
    return {"title": event.title, "description": event.description, "questions": event.questions,
            "registration_open": event.registration_open, "revision": event.revision,
            "response_retention_days": event.response_retention_days, **changes}


@pytest.mark.asyncio
async def test_form_enrollment_waits_for_final_answer_and_persists_no_profile_fields(repository):
    questions = [question(), question("single_choice"), question("multiple_choice"), question(required=False)]
    events, event = await configured(repository, questions)
    await registered(repository, 200)
    assert (await events.visit(200, event.id))[1] == "needs_form"
    assert (await events.members(100, event.id)).total == 0
    survey = EventSurvey(events)
    step = await survey.begin(200, event.id)
    step, _ = await survey.respond(200, text="A temporary answer")
    first_token = step.token
    step, _ = await survey.respond(200, token=step.token, action="choose", option=1)
    with pytest.raises(EventError, match="earlier question"):
        await survey.respond(200, token=first_token, action="choose", option=0)
    step, _ = await survey.respond(200, token=step.token, action="toggle", option=0)
    step, _ = await survey.respond(200, token=step.token, action="next")
    assert step.index == 3 and (await events.members(100, event.id)).total == 0
    step, completed = await survey.respond(200, token=step.token, action="skip")
    assert step is None and completed.id == event.id
    async with repository.db.transaction() as session:
        answers = (await session.scalars(select(EventAnswers))).one()
        assert answers.answers == {questions[0]["id"]: "A temporary answer", questions[1]["id"]: "Option B",
                                   questions[2]["id"]: ["Option A"]}
        assert answers.expires_at - answers.submitted_at == timedelta(days=30)
        assert await session.get(EventFormSession, 200) is None
        assert await session.scalar(select(func.count()).select_from(PendingEventRegistration)) == 0
        user = await session.get(TelegramUser, 200)
        assert user.education_level == "Level 4" and not hasattr(user, "answers")
    assert (await events.visit(200, event.id))[1] == "already_registered"


@pytest.mark.asyncio
async def test_new_students_finish_account_registration_before_event_questions(repository):
    events, event = await configured(repository)
    plain = await events.create(100, "No form")
    await events.visit(200, event.id)
    await events.visit(200, plain.id)
    await registered(repository, 200)
    assert (await events.members(100, plain.id)).total == 1
    assert (await events.members(100, event.id)).total == 0
    assert [item.id for item in await events.pending_forms(200)] == [event.id]
    step = await EventSurvey(events).resume(200)
    assert step.event.id == event.id


@pytest.mark.asyncio
async def test_chat_progress_survives_restart_and_expires_after_one_hour(repository):
    events, event = await configured(repository, [question(), question()])
    await registered(repository, 200)
    await events.visit(200, event.id)
    survey = EventSurvey(events)
    await survey.begin(200, event.id)
    await survey.respond(200, text="Partial answer")
    assert (await EventSurvey(events).resume(200)).index == 1
    repository.test_clock[0] += timedelta(hours=1, seconds=1)
    with pytest.raises(EventError, match="expired"):
        await survey.respond(200, text="Too late")
    await events.purge_answers()
    async with repository.db.transaction() as session:
        assert await session.get(EventFormSession, 200) is None
    assert (await survey.resume(200)).index == 0


@pytest.mark.asyncio
async def test_expired_answers_are_hidden_and_deleted_but_enrollment_remains(repository):
    events, event = await configured(repository)
    await registered(repository, 200)
    await events.submit_form(200, event.id, {event.questions[0]["id"]: "Temporary"}, event.form_revision)
    assert (await events.answer_page(100, event.id)).members[0]["answers"]
    repository.test_clock[0] += timedelta(days=30)
    assert (await events.answer_page(100, event.id)).members[0]["answers"] is None
    assert await events.purge_answers() == 1
    assert (await events.members(100, event.id)).total == 1


@pytest.mark.asyncio
async def test_retention_can_shorten_but_never_extend_existing_answer_lifetimes(repository):
    events, event = await configured(repository)
    await registered(repository, 200)
    await events.submit_form(200, event.id, {event.questions[0]["id"]: "Temporary"}, event.form_revision)
    event = await events.configure(100, event.id, configuration(event, response_retention_days=7))
    event = await events.configure(100, event.id, configuration(event, response_retention_days=90))
    async with repository.db.transaction() as session:
        answers = (await session.scalars(select(EventAnswers))).one()
        assert answers.expires_at - answers.submitted_at == timedelta(days=7)


@pytest.mark.asyncio
async def test_owner_controls_and_form_lock_survive_answer_deletion(repository):
    events, event = await configured(repository)
    await registered(repository, 200)
    for operation in (events.settings(200, event.id), events.configure(200, event.id, configuration(event)),
                      events.answer_page(200, event.id), events.purge_answers(200, event.id)):
        with pytest.raises(EventError, match="organizer"):
            await operation
    with pytest.raises(EventError, match="another window"):
        await events.configure(100, event.id, configuration(event, revision=event.revision - 1))
    await events.submit_form(200, event.id, {event.questions[0]["id"]: "Temporary"}, event.form_revision)
    assert await events.purge_answers(100, event.id) == 1
    with pytest.raises(EventError, match="locked"):
        await events.configure(100, event.id, configuration(event, questions=[question()]))


@pytest.mark.asyncio
async def test_required_choices_and_invalid_options_do_not_advance(repository):
    events, event = await configured(repository, [question("multiple_choice")])
    await registered(repository, 200)
    survey = EventSurvey(events)
    step = await survey.begin(200, event.id)
    for kwargs, message in [({"text": "Option A"}, "inline buttons"),
                            ({"token": step.token, "action": "next"}, "Please answer"),
                            ({"token": step.token, "action": "toggle", "option": 100}, "valid option"),
                            ({"token": step.token, "action": "skip"}, "inline buttons")]:
        with pytest.raises(EventError, match=message):
            await survey.respond(200, **kwargs)
    step, _ = await survey.respond(200, token=step.token, action="toggle", option=1)
    step, _ = await survey.respond(200, token=step.token, action="toggle", option=1)
    assert step.answers[step.question["id"]] == []
    assert (await survey.resume(200)).index == 0


@pytest.mark.asyncio
async def test_changed_form_restarts_progress_and_closed_event_cannot_enroll(repository):
    events, event = await configured(repository)
    await registered(repository, 200)
    await events.visit(200, event.id)
    survey = EventSurvey(events)
    step = await survey.begin(200, event.id)
    event = await events.configure(100, event.id, configuration(event, questions=[question(label="Updated")]))
    with pytest.raises(EventError, match="updated"):
        await survey.respond(200, text="Old answer")
    current = await survey.resume(200)
    assert current.question["label"] == "Updated" and current.token != step.token
    await events.configure(100, event.id, configuration(event, registration_open=False))
    with pytest.raises(EventError, match="closed"):
        await survey.respond(200, text="Blocked")
    with pytest.raises(EventError, match="closed"):
        await events.visit(200, event.id)
    assert await survey.cancel(200)
    assert not await survey.active(200)
    assert await events.pending_forms(200) == []


@pytest.mark.asyncio
async def test_changing_event_details_keeps_questionnaire_progress_and_button_tokens(repository):
    events, event = await configured(repository, [question(), question("single_choice")])
    await registered(repository, 200)
    await events.visit(200, event.id)
    survey = EventSurvey(events)
    await survey.begin(200, event.id)
    step, _ = await survey.respond(200, text="Keep this answer")
    event = await events.configure(100, event.id, configuration(event, title="Renamed", response_retention_days=7))
    current = await survey.resume(200)
    assert current.token == step.token and current.index == 1
    assert current.answers == step.answers
    _, completed = await survey.respond(200, token=current.token, action="choose", option=0)
    assert completed.title == "Renamed"
    async with repository.db.transaction() as session:
        response = (await session.scalars(select(EventAnswers))).one()
        assert response.expires_at - response.submitted_at == timedelta(days=7)


@pytest.mark.asyncio
async def test_simultaneous_last_answers_create_one_registration_and_one_answer_set(repository):
    events, event = await configured(repository)
    await registered(repository, 200)
    survey = EventSurvey(events)
    await survey.begin(200, event.id)
    results = await asyncio.gather(survey.respond(200, text="First"), survey.respond(200, text="Second"), return_exceptions=True)
    assert sum(isinstance(result, EventError) for result in results) == 1
    async with repository.db.transaction() as session:
        assert await session.scalar(select(func.count()).select_from(EventRegistration)) == 1
        assert await session.scalar(select(func.count()).select_from(EventAnswers)) == 1


@pytest.mark.parametrize("bad", [None, {}, [question()] * 21, [question("unknown")],
    [{**question(), "id": "bad"}], [{**question(), "label": " "}], [{**question(), "type": []}],
    [{**question("single_choice"), "options": ["Same", "Same"]}], [{**question(), "required": "true"}]])
def test_question_definitions_are_bounded_and_validated(bad):
    with pytest.raises(EventError):
        validate_questions(bad)


@pytest.mark.parametrize("kind,value", [("text", "x" * 2001), ("number", "nan"), ("number", "inf"),
    ("single_choice", "Missing"), ("multiple_choice", ["Missing"]), ("multiple_choice", ["Option A", "Option A"])])
def test_invalid_answers_are_rejected(kind, value):
    item = question(kind)
    with pytest.raises(EventError):
        validate_answers([item], {item["id"]: value})
