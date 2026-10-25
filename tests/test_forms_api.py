from uuid import uuid4

import pytest

from app.miniapp.state import BROADCASTS
from tests import test_miniapp
from tests.test_miniapp import headers

miniapp_client = test_miniapp.client


@pytest.mark.asyncio
async def test_forms_alias_supports_departments_columns_cell_edits_and_private_audiences(
    miniapp_client,
):
    client = miniapp_client
    form_id = client.event_id
    prefix = f"/api/forms/{form_id}"
    forms = await (await client.get("/api/forms", headers=headers())).json()
    assert forms["forms"][0]["id"] == form_id
    form = await (await client.get(prefix, headers=headers())).json()
    assert "kind" not in form and "kind" not in forms["forms"][0]
    body = {
        key: form[key]
        for key in [
            "title",
            "description",
            "registration_open",
            "response_retention_days",
            "questions",
            "revision",
        ]
    }
    response = await client.put(prefix, headers=headers(), json={**body, "department": "SU"})
    assert response.status == 200
    saved = await response.json()
    assert saved["department"] == "SU" and "kind" not in saved
    await client.events.visit(200, form_id)
    column = {"id": str(uuid4()), "label": "Shortlisted", "type": "checkbox", "options": []}
    assert (
        await client.put(
            prefix + "/columns", headers=headers(), json={"columns": [column], "revision": 1}
        )
    ).status == 200
    page = await (await client.get(prefix + "/members", headers=headers())).json()
    assert page["columns"] == [column] and page["columns_revision"] == 2
    value = {
        "scope": "column",
        "field": column["id"],
        "value": True,
        "revision": 1,
        "columns_revision": 2,
    }
    assert (
        await client.patch(prefix + "/members/200", headers=headers(), json=value)
    ).status == 200
    assert (
        await client.patch(prefix + "/members/200", headers=headers(), json=value)
    ).status == 400
    state = await (await client.get(prefix + "/members", headers=headers())).json()
    assert state["members"][0]["organizer_values"] == {column["id"]: True}
    draft_data = {"recipient_ids": [200], "request_id": str(uuid4())}
    response = await client.post(prefix + "/broadcasts", headers=headers(), json=draft_data)
    assert response.status == 201
    draft = await response.json()
    assert draft["compose_url"].endswith("compose_" + draft["id"]) and draft["status"] == "draft"
    assert await client.server.app[BROADCASTS].claim() is None
    for method, path, data in [
        ("get", prefix + "/members", None),
        ("put", prefix + "/columns", {"columns": [], "revision": 2}),
        ("patch", prefix + "/members/200", value),
        ("post", prefix + "/broadcasts", draft_data),
        ("get", prefix + "/broadcasts", None),
        ("post", prefix + "/broadcasts/" + draft["id"] + "/cancel", None),
    ]:
        result = await getattr(client, method)(path, json=data)
        assert result.status == 401
        # Even a registered organizer for another form cannot manage this one.
        await client.events.create(200, "Other owner")
        result = await getattr(client, method)(path, headers=headers(200), json=data)
        assert result.status == 400
    history = await (await client.get(prefix + "/broadcasts", headers=headers())).json()
    assert history["total"] == 1 and history["broadcasts"][0]["status"] == "draft"
    assert (
        await client.post(prefix + "/broadcasts/" + draft["id"] + "/cancel", headers=headers())
    ).status == 200


@pytest.mark.asyncio
async def test_table_api_rejects_forged_identity_profile_writes_and_invalid_values(miniapp_client):
    client = miniapp_client
    prefix = f"/api/forms/{client.event_id}"
    await client.events.visit(200, client.event_id)
    data = {
        "scope": "profile",
        "field": "email",
        "value": "attacker@example.test",
        "revision": 1,
        "columns_revision": 1,
    }
    assert (
        await client.patch(prefix + "/members/200?user_id=100", headers=headers(200), json=data)
    ).status == 403
    assert (await client.patch(prefix + "/members/200", headers=headers(), json=data)).status == 400
    for value in [None, [], {"unexpected": True}]:
        result = await client.put(prefix + "/columns", headers=headers(), json=value)
        assert result.status == 400
    result = await client.post(
        prefix + "/broadcasts",
        headers=headers(),
        json={"recipient_ids": [100], "request_id": str(uuid4())},
    )
    assert result.status == 400


@pytest.mark.asyncio
async def test_finished_messages_have_private_owner_checked_links_and_hide_drafts(miniapp_client):
    client = miniapp_client
    prefix = f"/api/forms/{client.event_id}/broadcasts"
    await client.events.visit(200, client.event_id)
    repository = client.server.app[BROADCASTS]
    draft = await repository.create(100, client.event_id, [200], str(uuid4()))
    await repository.compose(100, draft["id"], 500)
    ready = await repository.preview(100, draft["id"], 500, 600, "text", original_message_id=400)
    await repository.queue(100, draft["id"], ready["revision"])
    await repository.finish(await repository.claim(), "sent", message_id=700)
    await repository.create(100, client.event_id, [200], str(uuid4()))

    response = await client.get(prefix + "?status=completed", headers=headers())
    assert response.status == 200
    history = await response.json()
    assert history["total"] == 1 and not history["has_active"]
    item = history["broadcasts"][0]
    assert item["id"] == draft["id"] and item["status"] == "completed"
    assert item["message_url"] == f"https://t.me/example_bot?start=message_{draft['id']}"
    assert (await client.get(prefix + "?status=completed")).status == 401
    assert (
        await client.get(prefix + "?status=completed&user_id=100", headers=headers(200))
    ).status == 403
    assert (await client.get(prefix + "?status=draft", headers=headers())).status == 400
