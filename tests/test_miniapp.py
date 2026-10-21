from datetime import datetime, timezone
import hashlib
import hmac
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlencode

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest
import pytest_asyncio

from app.event_repository import EventRepository
from app.miniapp import create_web_app, validate_init_data
from registrar.models import Student

TOKEN = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789"


def signed(user_id=100, *, age=0, **extra):
    values = {"auth_date": str(int(datetime.now(timezone.utc).timestamp()) - age),
              "user": json.dumps({"id": user_id, "first_name": "Student", "is_bot": False}), **extra}
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    signature = hmac.new(secret, "\n".join(f"{key}={value}" for key, value in sorted(values.items())).encode(), hashlib.sha256).hexdigest()
    return urlencode({**values, "hash": signature})


def headers(user_id=100):
    return {"Authorization": "tma " + signed(user_id)}


@pytest_asyncio.fixture
async def client(repository):
    for user_id in (100, 200):
        person = Student(str(user_id), "Student", f"{user_id}@example.test", account=f"{user_id}@example.test")
        await repository.reserve_code(user_id, person, "123456")
        await repository.consume_code(user_id, "123456")
        await repository.save_contact(user_id, user_id, "+998901234567")
        await repository.complete_registration(user_id, "CIFS")
    events = EventRepository(repository.db, clock=repository.clock)
    event = await events.create(100, "Owner's event <script>")
    bot = SimpleNamespace(token=TOKEN, me=AsyncMock(return_value=SimpleNamespace(username="example_bot")))
    async with TestClient(TestServer(create_web_app(events, bot))) as instance:
        instance.event_id = event.id
        instance.events = events
        yield instance


@pytest.mark.parametrize("raw", ["", "user=forged", signed(age=3601), signed(age=-120),
    signed(user_id=0), signed(user='{"id":100,"first_name":"Bot","is_bot":true}'),
    signed() + "&user=duplicate", signed().replace("Student", "Changed")])
def test_auth_rejects_forged_expired_future_duplicate_and_bot_data(raw):
    with pytest.raises(web.HTTPUnauthorized):
        validate_init_data(raw, TOKEN)


def test_auth_accepts_signed_fields_including_telegram_signature():
    assert validate_init_data(signed(signature="telegram-ed25519-signature"), TOKEN) == 100


@pytest.mark.asyncio
async def test_static_assets_are_public_but_api_always_needs_telegram_auth(client):
    response = await client.get("/")
    assert response.status == 200 and "Event Studio" in await response.text()
    assert "no-store" == response.headers["Cache-Control"]
    assert "frame-ancestors" in response.headers["Content-Security-Policy"]
    for name in ("app.js", "style.css", "style.svg"):
        asset = await client.get(f"/assets/{name}")
        assert asset.status == 200
        assert asset.headers["Cache-Control"] == "no-store"
    for name in ("package.json", "main.tsx", "app.js.map", ".env"):
        assert (await client.get(f"/assets/{name}")).status == 404
    for path in ("/api/session", "/api/events", f"/api/events/{client.event_id}",
                 f"/api/events/{client.event_id}/members", f"/api/events/{client.event_id}/qr"):
        response = await client.get(path)
        assert response.status == 401
    assert (await client.get("/assets/.env")).status == 404


@pytest.mark.asyncio
async def test_owner_can_configure_event_and_view_qr_and_participants(client):
    response = await client.get("/api/events", headers=headers())
    data = await response.json()
    assert data["total"] == 1 and data["events"][0]["members"] == 0
    response = await client.get(f"/api/events/{client.event_id}", headers=headers())
    event = await response.json()
    assert event["link"] == f"https://t.me/example_bot?start=event_{client.event_id}"
    body = {key: event[key] for key in ("title", "description", "registration_open", "questions", "revision", "response_retention_days")}
    body["description"] = "A revised description"
    response = await client.put(f"/api/events/{client.event_id}", headers=headers(), json=body)
    assert response.status == 200 and (await response.json())["revision"] == 2
    response = await client.put(f"/api/events/{client.event_id}", headers=headers(), json=body)
    assert response.status == 400 and "another window" in (await response.json())["error"]
    qr = await client.get(f"/api/events/{client.event_id}/qr", headers=headers())
    assert qr.headers["Content-Type"] == "image/png"
    assert qr.headers["Content-Disposition"] == f'attachment; filename="event-{client.event_id}.png"'
    assert (await qr.read()).startswith(b"\x89PNG\r\n\x1a\n")
    response = await client.get(f"/api/events/{client.event_id}/members", headers=headers())
    assert (await response.json())["total"] == 0


@pytest.mark.asyncio
async def test_other_registered_users_cannot_access_any_event_management_endpoint(client):
    response = await client.get("/api/events", headers=headers(200))
    assert response.status == 403 and "/new_event" in (await response.json())["error"]
    own_event = await client.events.create(200, "Another organizer's event")
    response = await client.get("/api/events", headers=headers(200))
    assert [event["id"] for event in (await response.json())["events"]] == [own_event.id]
    for suffix in ("", "/members", "/qr"):
        response = await client.get(f"/api/events/{client.event_id}{suffix}", headers=headers(200))
        assert response.status == 400 and "organizer" in (await response.json())["error"]
    response = await client.delete(f"/api/events/{client.event_id}/answers", headers=headers(200))
    assert response.status == 400


@pytest.mark.asyncio
async def test_invalid_api_input_is_rejected_without_internal_error_details(client):
    for query in ("-1", "bad", "99999999999"):
        response = await client.get("/api/events?page=" + query, headers=headers())
        assert response.status == 400
    response = await client.put(f"/api/events/{client.event_id}", headers=headers(), data="not-json")
    assert response.status == 400
    response = await client.get("/api/events", headers=headers(999999))
    assert response.status == 403 and "Complete registration" in (await response.json())["error"]


@pytest.mark.asyncio
async def test_registered_non_organizer_is_denied_every_api_endpoint_until_creating_event(client):
    paths = ("/api/session", "/api/events", f"/api/events/{client.event_id}",
             f"/api/events/{client.event_id}/members", f"/api/events/{client.event_id}/qr")
    for path in paths:
        response = await client.get(path, headers=headers(200))
        assert response.status == 403 and "/new_event" in (await response.json())["error"]
    for method, path in ((client.put, f"/api/events/{client.event_id}"),
                         (client.delete, f"/api/events/{client.event_id}/answers")):
        response = await method(path, headers=headers(200))
        assert response.status == 403
    await client.events.visit(200, client.event_id)
    assert (await client.get("/api/session", headers=headers(200))).status == 403
    await client.events.create(200, "First event")
    assert (await client.get("/api/session", headers=headers(200))).status == 200
