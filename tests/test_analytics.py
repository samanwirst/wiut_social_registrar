import asyncio
import json
from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy import func, select

from app.analytics.auth import AdminAuth, LoginError, hash_password
from app.analytics.collector import UsageCollector
from app.analytics.events import record
from app.analytics.models import AdminChallenge, AdminSession, UsageEvent
from app.analytics.queries import AnalyticsQueries, date_range
from app.event_repository import EventRepository
from app.miniapp import create_web_app
from app.miniapp.analytics_routes import PENDING_COOKIE, SESSION_COOKIE, AdminPortal
from app.surveys import EventSurvey
from tests import test_bot
from tests.helpers import TEST_TOKEN, signed_init_data
from tests.test_bot import callback, send
from tests.test_event_forms import configured, question, registered

PASSWORD = "synthetic123!"
PASSWORD_HASH = hash_password(PASSWORD, salt=b"x" * 16)
bot_app = test_bot.app


def auth(repository, bot=None, **overrides):
    return AdminAuth(
        repository.db,
        bot or SimpleNamespace(send_message=AsyncMock()),
        admin_ids=overrides.get("admin_ids", (100,)),
        password_hash=overrides.get("password_hash", PASSWORD_HASH),
        secret="ab" * 32,
        clock=repository.clock,
    )


def sent_code(instance):
    # Test-only synthetic transport; never prints a real code or contacts Telegram.
    return (
        instance.bot.send_message.await_args.kwargs["text"]
        .split("Your one-time code: ")[1]
        .split("\n")[0]
    )


@pytest.mark.asyncio
async def test_code_is_copyable_and_accepts_clipboard_formatting_without_losing_zeroes(
    repository, monkeypatch
):
    monkeypatch.setattr("app.analytics.auth.secrets.randbelow", lambda maximum: 42)
    instance = auth(repository)
    result, browser = await instance.request(100, PASSWORD)
    code = sent_code(instance)
    assert code == "000042"
    delivered = instance.bot.send_message.await_args.kwargs
    assert not delivered.get("protect_content") and delivered["parse_mode"] is None
    entity = next(item for item in delivered["entities"] if item.type == "code")
    text = delivered["text"].encode("utf-16-le")
    assert text[entity.offset * 2 : (entity.offset + entity.length) * 2].decode("utf-16-le") == code
    for malformed in (code + "7", code[:-1], code + "x"):
        with pytest.raises(LoginError, match="Incorrect code"):
            await instance.verify(result["challenge_id"], browser, malformed)
    token = await instance.verify(
        result["challenge_id"], browser, f"\u200e{code[:3]}\u00a0{code[3:]}\u200f\r\n"
    )
    assert await instance.authenticate(token) == 100
    with pytest.raises(LoginError):
        await instance.verify(result["challenge_id"], browser, code)


@pytest.mark.asyncio
async def test_password_telegram_code_browser_binding_one_use_and_session_revocation(repository):
    instance = auth(repository)
    with pytest.raises(LoginError):
        await instance.request(200, PASSWORD)
    assert instance.bot.send_message.await_count == 0
    result, browser = await instance.request(100, PASSWORD)
    code = sent_code(instance)
    with pytest.raises(LoginError):
        await instance.verify(result["challenge_id"], "another browser", code)
    with pytest.raises(LoginError):
        await instance.verify(
            result["challenge_id"], browser, "999999" if code != "999999" else "111111"
        )
    async with repository.db.transaction() as session:
        row = await session.get(AdminChallenge, result["challenge_id"])
        assert row.attempts_left == 4 and code not in row.code_hash and browser != row.browser_hash
    token = await instance.verify(result["challenge_id"], browser, code)
    assert await instance.authenticate(token) == 100
    assert await auth(repository).authenticate(token) == 100  # Survives application recreation.
    with pytest.raises(LoginError):
        await instance.verify(result["challenge_id"], browser, code)
    with pytest.raises(LoginError):
        await instance.authenticate(token, csrf="wrong")
    assert await instance.authenticate(token, csrf=instance.csrf(token)) == 100
    with pytest.raises(LoginError):
        await auth(repository, admin_ids=(200,)).authenticate(token)
    with pytest.raises(LoginError):
        await auth(
            repository, password_hash=hash_password("a different long password")
        ).authenticate(token)
    async with repository.db.transaction() as session:
        stored = await session.get(AdminSession, instance.digest(token))
        assert stored.token_hash != token and stored.csrf_hash != instance.csrf(token)
    await instance.logout(token)
    with pytest.raises(LoginError):
        await instance.authenticate(token)


@pytest.mark.asyncio
async def test_login_delivery_failure_expiry_attempt_limit_and_persistent_throttling(repository):
    bot = SimpleNamespace(send_message=AsyncMock(side_effect=TimeoutError))
    instance = auth(repository, bot)
    with pytest.raises(LoginError) as failure:
        await instance.request(100, PASSWORD)
    assert failure.value.status == 503
    async with repository.db.transaction() as session:
        assert await session.scalar(select(func.count()).select_from(AdminChallenge)) == 0
    bot.send_message.side_effect = None
    result, browser = await instance.request(100, PASSWORD)
    code = sent_code(instance)
    for _ in range(5):
        with pytest.raises(LoginError):
            await instance.verify(result["challenge_id"], browser, "invalid")
    with pytest.raises(LoginError):
        await instance.verify(result["challenge_id"], browser, code)
    repository.test_clock[0] += timedelta(minutes=2)
    result, browser = await instance.request(100, PASSWORD)
    repository.test_clock[0] += timedelta(minutes=5)
    with pytest.raises(LoginError):
        await instance.verify(result["challenge_id"], browser, sent_code(instance))
    for _ in range(2):
        with pytest.raises(LoginError):
            await auth(repository).request(100, "wrong password long enough")
    with pytest.raises(LoginError) as limited:
        await auth(repository).request(100, PASSWORD)
    assert limited.value.status == 429


@pytest.mark.asyncio
async def test_concurrent_code_consumption_has_one_winner_and_idle_sessions_expire(repository):
    instance = auth(repository)
    result, browser = await instance.request(100, PASSWORD)
    results = await asyncio.gather(
        *[instance.verify(result["challenge_id"], browser, sent_code(instance)) for _ in range(2)],
        return_exceptions=True,
    )
    tokens = [value for value in results if isinstance(value, str)]
    assert (
        len(tokens) == 1 and len([value for value in results if isinstance(value, LoginError)]) == 1
    )
    repository.test_clock[0] += timedelta(minutes=31)
    with pytest.raises(LoginError):
        await instance.authenticate(tokens[0])


@pytest.mark.asyncio
async def test_usage_ingestion_is_bounded_deduplicated_typed_and_failure_isolated(
    repository, monkeypatch
):
    collector = UsageCollector(repository.db, clock=repository.clock)
    await collector.start()
    session_id, event_id, form_id = [str(uuid4()) for _ in range(3)]
    event = {
        "id": event_id,
        "name": "ui_action",
        "action": "save_form",
        "form_id": form_id,
        "email": "secret@example.test",
        "answer": "PRIVATE ANSWER",
        "token": "PRIVATE TOKEN",
        "source": "server",
        "user_id": 999,
        "screen": ["bad"],
        "platform": {"secret": "bad"},
        "route": "GET /api/private",
        "duration_ms": 100,
    }
    try:
        for _ in range(2):
            assert collector.client_batch(100, session_id, [event])
        await collector.flush()
        async with repository.db.transaction() as session:
            rows = (await session.scalars(select(UsageEvent))).all()
            assert len(rows) == 1 and rows[0].user_id == 100 and rows[0].source == "miniapp"
            assert rows[0].properties == {"action": "save_form"}
        with pytest.raises(ValueError):
            collector.client_batch(100, session_id, [{"name": "form_completed"}])
        with pytest.raises(ValueError):
            collector.client_batch(100, session_id, [{"name": ["bad"]}])
        for _ in range(5):
            assert collector.client_batch(100, session_id, [{"name": "screen_view"}] * 20)
        assert not collector.client_batch(100, session_id, [{"name": "screen_view"}] * 20)
        collector.queue = asyncio.Queue(maxsize=1)
        collector.emit("chat_action", user_id=100)
        collector.emit("chat_action", user_id=100)
        assert collector.dropped == 1

        @asynccontextmanager
        async def fail(*args, **kwargs):
            raise RuntimeError("synthetic database failure")
            yield

        monkeypatch.setattr(repository.db, "transaction", fail)
        # Restore before background processing: explicitly test the flush failure branch.
        await collector.flush()
        assert collector.failures == 1 and collector.dropped == 2
    finally:
        await collector.close()


@pytest.mark.asyncio
async def test_form_milestones_restart_privacy_and_transaction_rollback(repository, monkeypatch):
    await registered(repository, 200)
    events, form = await configured(repository, [question(), question("single_choice")])
    async with repository.db.transaction(write=True) as session:
        from app.models import Event

        stored = await session.get(Event, form.id)
        stored.anonymous = True
    form, _ = await events.visit(200, form.id)
    survey = EventSurvey(events)
    step = await survey.begin(200, form.id)
    first_token = step.token
    resumed = await EventSurvey(events).resume(200)
    assert resumed.token == first_token
    step, _ = await survey.respond(200, text="PRIVATE LONG ANSWER")
    async with repository.db.transaction() as session:
        rows = (
            await session.scalars(select(UsageEvent).where(UsageEvent.form_id == form.id))
        ).all()
        student_rows = [
            row
            for row in rows
            if row.name in {"form_opened", "form_started", "question_reached", "question_answered"}
        ]
        assert student_rows and all(row.user_id is None for row in student_rows)
        assert "PRIVATE LONG ANSWER" not in json.dumps([row.properties for row in rows])
    start, end = repository.clock() - timedelta(days=1), repository.clock() + timedelta(days=1)
    report = await AnalyticsQueries(repository.db, "ab" * 32, clock=repository.clock).form(
        form.id, start, end
    )
    assert report["questions"][0]["reached"] == 1 and report["questions"][0]["answered"] == 1
    original = events.enrollment.submit_answers_in_transaction

    async def fail_after_submit(*args, **kwargs):
        await original(*args, **kwargs)
        raise RuntimeError("synthetic final enrollment failure")

    # configured() uses text, number, choice questions; finish the remaining steps first.
    while step and step.index + 1 < len(form.questions):
        kwargs = (
            {"text": "2"}
            if step.question["type"] == "number"
            else {"action": "choose", "option": 0, "token": step.token}
        )
        step, _ = await survey.respond(200, **kwargs)
    monkeypatch.setattr(events.enrollment, "submit_answers_in_transaction", fail_after_submit)
    with pytest.raises(RuntimeError):
        kwargs = (
            {"text": "2"}
            if step.question["type"] in {"text", "number"}
            else {"action": "choose", "option": 0, "token": step.token}
        )
        await survey.respond(200, **kwargs)
    async with repository.db.transaction() as session:
        assert not await session.scalar(
            select(UsageEvent.id).where(
                UsageEvent.form_id == form.id, UsageEvent.name == "form_completed"
            )
        )


@pytest.mark.asyncio
async def test_aggregate_funnel_cohort_anonymous_omission_and_retention(repository):
    await registered(repository, 100)
    events = EventRepository(repository.db, clock=repository.clock)
    form = await events.create(100, "Synthetic campus event")
    now = repository.clock()
    async with repository.db.transaction(write=True) as session:
        for name, outcome, data in [
            ("chat_action", "ok", {"action": "start"}),
            (
                "http_request",
                "error",
                {"route": "GET /api/forms", "error": "database", "status_code": 503},
            ),
            ("screen_engagement", "ok", {"screen": "qr"}),
        ]:
            record(
                session,
                name,
                at=now,
                user_id=100,
                form_id=form.id,
                duration_ms=2500,
                outcome=outcome,
                **data,
            )
    queries = AnalyticsQueries(repository.db, "ab" * 32, clock=repository.clock)
    start, end = now - timedelta(days=1), now + timedelta(days=1)
    summary = await queries.summary(start, end)
    assert summary["inventory"]["users"] == 2 and summary["inventory"]["registered"] == 1
    assert [step["users"] for step in summary["registration_funnel"]] == [2, 1, 1, 1, 1]
    assert summary["performance"][0]["average_ms"] == 2500
    assert summary["issues"][0]["category"] == "database"
    assert (await queries.forms(start, end))["forms"][0]["title"] == form.title
    assert (await queries.users(start, end))["users"][0]["label"].startswith("User ")
    assert (await queries.retention(start, end))[0]["eligible"] == 0
    timeline = await queries.timeline(start, end, user_id=100)
    serialized = json.dumps(timeline)
    assert "example.test" not in serialized and "requested_student_id" not in serialized
    assert timeline["registration_history"]
    with pytest.raises(ValueError):
        date_range("2026-02-31", "2026-03-01", now=now)


@pytest.mark.asyncio
async def test_admin_http_two_factors_cookie_headers_csrf_and_signed_ingestion(repository):
    await registered(repository, 100)
    events = EventRepository(repository.db, clock=repository.clock)
    event = await events.create(100, "Synthetic form")
    await registered(repository, 200)
    other = await events.create(200, "Another form")
    bot = SimpleNamespace(token=TEST_TOKEN, send_message=AsyncMock())
    collector = UsageCollector(repository.db, clock=repository.clock)
    instance = auth(repository, bot)
    portal = AdminPortal(
        instance,
        AnalyticsQueries(repository.db, "ab" * 32, clock=repository.clock),
        "https://analytics.example.test",
        collector,
    )
    app = create_web_app(events, bot, usage_collector=collector, admin_portal=portal)
    async with TestClient(TestServer(app)) as client:
        headers = {"Origin": portal.origin, "X-Analytics-Request": "1"}
        assert (await client.get("/admin/api/summary")).status == 401
        assert (
            await client.get(
                "/admin/api/summary?user_id=100",
                headers={"Authorization": "tma " + signed_init_data()},
            )
        ).status == 401
        assert (
            await client.post("/admin/api/login", json={"telegram_id": "100", "password": PASSWORD})
        ).status == 403
        response = await client.post(
            "/admin/api/login", headers=headers, json={"telegram_id": "100", "password": PASSWORD}
        )
        assert response.status == 200
        result = await response.json()
        pending = response.cookies[PENDING_COOKIE]
        assert pending["secure"] and pending["httponly"] and pending["samesite"] == "Strict"
        assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
        assert (await client.get("/admin/api/summary")).status == 401
        response = await client.post(
            "/admin/api/verify",
            headers={**headers, "Cookie": f"{PENDING_COOKIE}={pending.value}"},
            json={"challenge_id": result["challenge_id"], "code": sent_code(instance)},
        )
        assert response.status == 200
        token = response.cookies[SESSION_COOKIE].value
        cookies = {"Cookie": f"{SESSION_COOKIE}={token}"}
        response = await client.get("/admin/api/session", headers=cookies)
        csrf = (await response.json())["csrf"]
        assert (
            await client.get("/admin/api/summary?start=2026-10-01&end=2026-10-31", headers=cookies)
        ).status == 200
        assert (await client.get("/admin/api/forms", headers=cookies)).status == 200
        assert (
            await client.post("/admin/api/logout", headers={**headers, **cookies})
        ).status == 403
        assert (
            await client.post(
                "/admin/api/logout", headers={**headers, **cookies, "X-CSRF-Token": csrf}
            )
        ).status == 200
        assert (await client.get("/admin/api/session", headers=cookies)).status == 401
        payload = {
            "session_id": str(uuid4()),
            "events": [{"name": "screen_view", "form_id": event.id, "screen": "qr"}],
        }
        assert (await client.post("/api/analytics", json=payload)).status == 401
        signed = {"Authorization": "tma " + signed_init_data()}
        assert (await client.post("/api/analytics", headers=signed, json=payload)).status == 204
        payload["events"][0]["form_id"] = other.id
        assert (await client.post("/api/analytics", headers=signed, json=payload)).status == 400
        assert (await client.get("/api/forms", headers=cookies)).status == 401
    await collector.close()


@pytest.mark.asyncio
async def test_analytics_retention_leaves_business_data_intact(repository):
    collector = UsageCollector(repository.db, clock=repository.clock)
    async with repository.db.transaction(write=True) as session:
        record(session, "chat_action", at=repository.clock() - timedelta(days=91), user_id=100)
        record(session, "chat_action", at=repository.clock(), user_id=200)
    await collector.purge()
    async with repository.db.transaction() as session:
        assert await session.scalar(select(func.count()).select_from(UsageEvent)) == 1
    assert await repository.next_profile_field(100) is None


@pytest.mark.asyncio
async def test_form_conversion_uses_same_attempt_cohort_across_period_boundary(repository):
    events, form = await configured(repository)
    now = repository.clock()
    before, during = str(uuid4()), str(uuid4())
    async with repository.db.transaction(write=True) as session:
        for name, attempt, when in (
            ("question_reached", before, now - timedelta(days=2)),
            ("question_answered", before, now),
            ("question_reached", during, now),
        ):
            record(
                session,
                name,
                at=when,
                form_id=form.id,
                session_id=attempt,
                question_id=form.questions[0]["id"],
            )
    result = await AnalyticsQueries(repository.db, "ab" * 32, clock=repository.clock).form(
        form.id, now - timedelta(days=1), now + timedelta(days=1)
    )
    assert result["questions"][0]["reached"] == 1
    assert result["questions"][0]["answered"] == 0
    assert result["questions"][0]["conversion"] == 0


@pytest.mark.asyncio
async def test_append_only_migration_preserves_unfinished_questionnaire(repository):
    if repository.db.engine.dialect.name != "sqlite":
        pytest.skip("Historical migration is covered on isolated SQLite")
    from alembic import command
    from alembic.config import Config

    from app.models import EventFormSession

    events, form = await configured(repository, [question(), question()])
    await registered(repository, 200)
    await events.visit(200, form.id)
    survey = EventSurvey(events)
    await survey.begin(200, form.id)
    step, _ = await survey.respond(200, text="Synthetic partial draft")
    token = step.token

    def downgrade(connection):
        config = Config("alembic.ini")
        config.attributes["connection"] = connection
        command.downgrade(config, "0010_administrator_announcements")

    async with repository.db.engine.begin() as connection:
        await connection.run_sync(downgrade)
    await repository.db.migrate()
    async with repository.db.transaction() as session:
        saved = await session.get(EventFormSession, 200)
        assert saved.question_index == 1 and saved.token == token
        assert saved.answers[form.questions[0]["id"]] == "Synthetic partial draft"
        assert saved.analytics_id is None
    resumed = await EventSurvey(events).resume(200)
    assert resumed.index == 1 and resumed.token == token
    _, completed = await survey.respond(200, text="Synthetic final answer")
    assert completed.id == form.id


@pytest.mark.asyncio
async def test_retention_excludes_cohorts_without_a_complete_return_day(repository):
    from app.models import TelegramUser

    now = repository.clock()
    created = now - timedelta(days=8, hours=1)
    async with repository.db.transaction(write=True) as session:
        user = await session.get(TelegramUser, 100)
        user.created_at = created
        for day in (1, 7):
            record(
                session,
                "chat_action",
                at=created + timedelta(days=day),
                user_id=100,
                action="start",
            )
    queries = AnalyticsQueries(repository.db, "ab" * 32, clock=repository.clock)
    current = await queries.retention(now - timedelta(days=10), now)
    assert current[0]["eligible"] == current[0]["returned"] == 1
    assert current[1]["eligible"] == current[1]["returned"] == 1
    historical = await queries.retention(now - timedelta(days=10), now - timedelta(days=6))
    assert historical[1]["eligible"] == historical[1]["returned"] == 0


@pytest.mark.asyncio
async def test_real_dispatcher_covers_registration_and_anonymous_form_without_content(bot_app):
    app = bot_app
    await send(app, "/start")
    await send(app, "this is not an ID")
    await test_bot.register(app)
    await send(app, "/me")
    form = await app.event_repository.create(100, "Synthetic survey")
    form = await app.event_repository.configure(
        100,
        form.id,
        {
            "title": form.title,
            "description": "",
            "registration_open": True,
            "revision": form.revision,
            "response_retention_days": 30,
            "anonymous": True,
            "questions": [question(), question("single_choice")],
        },
    )
    await send(app, "/start event_" + form.id)
    await send(app, "PRIVATE QUESTION ANSWER")
    step = await app.event_survey.resume(100)
    await callback(app, f"form:{step.token}:choose:0")
    while not app.usage.queue.empty():
        await app.usage.flush()
    async with app.database.transaction() as session:
        rows = (await session.scalars(select(UsageEvent))).all()
        names = {row.name for row in rows}
        assert {
            "chat_action",
            "registration_prompt",
            "registration_rejected",
            "email_lookup",
            "form_completed",
            "question_answered",
        } <= names
        assert {
            row.properties.get("stage") for row in rows if row.name == "registration_prompt"
        } >= {"student_id", "email", "phone", "education"}
        form_actions = [
            row
            for row in rows
            if row.form_id == form.id
            and row.name in {"question_reached", "question_answered", "form_completed"}
        ]
        assert form_actions and all(row.user_id is None for row in form_actions)
        contents = json.dumps([row.properties for row in rows])
        assert "PRIVATE QUESTION ANSWER" not in contents and "example.test" not in contents
