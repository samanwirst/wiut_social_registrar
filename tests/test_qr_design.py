import asyncio
import base64
import json
import threading
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
import segno
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image, ImageDraw

from app.configuration.qr_images import QrImageSettings
from app.event_repository import EventRepository
from app.miniapp import create_web_app
from app.services.qr_art import QrDesignError, open_artwork, scan_verified, styled_qr_images
from app.services.qr_designer import (
    JOB_TTL,
    MAX_JOBS,
    CloudflareImages,
    QrDesignCooldown,
    QrDesigner,
)
from registrar.config import ConfigurationError
from registrar.models import Student
from tests.helpers import complete_student_registration
from tests.test_miniapp import TOKEN, headers

LINK = "https://t.me/example_bot?start=event_12345678-1234-4234-8234-123456789abc"


@pytest.fixture
def artwork():
    image = Image.new("RGB", (1024, 1024), "#083344")
    draw = ImageDraw.Draw(image)
    for y in range(0, 1024, 32):
        for x in range(0, 1024, 32):
            draw.rectangle((x, y, x + 31, y + 31), fill=(x % 256, y % 256, (x + y) % 256))
    result = BytesIO()
    image.save(result, format="PNG")
    return result.getvalue()


@pytest.mark.parametrize("transparent", [True, False])
def test_artistic_qr_has_exact_payload_alpha_and_scan_robustness(artwork, transparent):
    png = styled_qr_images(LINK, artwork)[transparent]
    with Image.open(BytesIO(png)) as image:
        assert scan_verified(image, LINK)
        assert not scan_verified(image, LINK + "different")
        assert image.mode == ("RGBA" if transparent else "RGB")
        assert image.width >= 1000
        if transparent:
            assert image.getchannel("A").getextrema() == (0, 255)
        else:
            assert image.getpixel((0, 0)) != (255, 255, 255)
        assert len(image.getcolors(1000000)) > 100


@pytest.mark.parametrize("data", [b"", b"not-an-image", b"x" * (8 * 1024 * 1024 + 1)])
def test_invalid_provider_images_are_rejected(data):
    with pytest.raises(QrDesignError, match="invalid image"):
        open_artwork(data)


def test_design_that_does_not_scan_is_never_exported(artwork, monkeypatch):
    monkeypatch.setattr("app.services.qr_art.scan_verified", lambda *_: False)
    with pytest.raises(QrDesignError, match="scan check"):
        styled_qr_images(LINK, artwork)


def test_illustration_stays_visible_with_rounded_eyes_and_a_clear_margin():
    art = Image.new("RGB", (512, 512), "white")
    draw = ImageDraw.Draw(art)
    draw.ellipse((80, 80, 432, 432), fill="#ff7300", outline="#270d42", width=12)
    draw.rectangle((235, 235, 277, 277), fill="white")
    encoded = BytesIO()
    art.save(encoded, format="PNG")
    images = styled_qr_images(LINK, encoded.getvalue())
    count = len(segno.make_qr(LINK, error="h").matrix)
    for transparent, png in images.items():
        with Image.open(BytesIO(png)).convert("RGBA") as image:
            assert scan_verified(image, LINK)
            scale = image.width // (count + 8)
            center = image.width // 2
            # Original bright artwork and enclosed white details survive; the
            # illustration isn't just darkened into the QR's module texture.
            assert image.getpixel((center, center)) == (255, 255, 255, 255)
            assert (
                sum(
                    n for n, color in image.getcolors(image.width**2) if color == (255, 115, 0, 255)
                )
                > 1000
            )
            # The finder eye is visibly rounded but keeps the 7:5:3 structure.
            corner = image.getpixel((4 * scale, 4 * scale))
            top = image.getpixel((7 * scale, 4 * scale))
            assert corner[3] == (0 if transparent else 255)
            assert top[3] == 255 and max(top[:3]) < 180
            if transparent:
                for strip in (
                    (0, 0, image.width, 4 * scale),
                    (0, 0, 4 * scale, image.height),
                    (0, image.height - 4 * scale, image.width, image.height),
                    (image.width - 4 * scale, 0, image.width, image.height),
                ):
                    assert image.crop(strip).getchannel("A").getextrema() == (0, 0)


@pytest.mark.parametrize("username", ["a_bot", "a" * 28 + "_bot"])
def test_both_design_backgrounds_scan_with_different_invitation_lengths(artwork, username):
    link = f"https://t.me/{username}?start=event_eb926819-6a22-4287-bc07-3c7b854ad693"
    images = styled_qr_images(link, artwork)
    assert set(images) == {True, False}
    for png in images.values():
        image = Image.open(BytesIO(png))
        assert scan_verified(image.rotate(90), link)


def test_blank_provider_artwork_is_not_presented_as_a_designed_qr():
    data = BytesIO()
    Image.new("RGB", (512, 512), "white").save(data, format="PNG")
    with pytest.raises(QrDesignError, match="empty illustration"):
        styled_qr_images(LINK, data.getvalue())


def test_layout_repair_checks_both_backgrounds_before_export(artwork, monkeypatch):
    checks = []

    def inspect(image, link):
        assert link == LINK
        checks.append(image.copy())
        # Reject the first opaque variant, requiring a smaller shared illustration.
        return len(checks) != 2

    monkeypatch.setattr("app.services.qr_art.scan_verified", inspect)
    images = styled_qr_images(LINK, artwork)
    assert len(checks) == 4 and set(images) == {True, False}
    assert checks[0].getpixel((0, 0))[3] == 0
    assert checks[1].getpixel((0, 0))[3] == 255
    assert checks[0].tobytes() != checks[2].tobytes()
    for png in images.values():
        assert scan_verified(Image.open(BytesIO(png)), LINK)


def test_optional_cloudflare_configuration_is_paired_and_private():
    assert not QrImageSettings.load({}).enabled
    with pytest.raises(ConfigurationError, match="both"):
        QrImageSettings.load({"CLOUDFLARE_API_TOKEN": "private-test-token"})
    with pytest.raises(ConfigurationError, match="32 hexadecimal"):
        QrImageSettings.load(
            {"CLOUDFLARE_ACCOUNT_ID": "wrong", "CLOUDFLARE_API_TOKEN": "private-test-token"}
        )
    settings = QrImageSettings.load(
        {"CLOUDFLARE_ACCOUNT_ID": "a" * 32, "CLOUDFLARE_API_TOKEN": "private-test-token"}
    )
    assert settings.enabled
    assert "private-test-token" not in repr(settings)
    assert "a" * 32 not in repr(settings)


@pytest.mark.asyncio
async def test_jobs_generate_both_backgrounds_once_and_expire(artwork):
    now = [0]
    provider = SimpleNamespace(generate=AsyncMock(return_value=artwork))
    designer = QrDesigner(provider=provider, clock=lambda: now[0])
    try:
        job = designer.submit(100, "event", LINK, "Voxel blocks")
        assert designer.get(200, "event", job.id) is None
        assert designer.get(100, "other-event", job.id) is None
        assert designer.submit(100, "event", LINK, "Again") is job
        await asyncio.gather(*designer.tasks)
        assert job.status == "ready" and set(job.images) == {True, False}
        provider.generate.assert_awaited_once_with("Voxel blocks")
        now[0] = 6.2
        assert designer.describe(job)["elapsed_seconds"] == 6
        assert designer.describe(job)["retry_after"] == 24
        with pytest.raises(QrDesignCooldown) as error:
            designer.submit(100, "event", LINK, "Another design")
        assert error.value.retry_after == 24
        now[0] = JOB_TTL + 1
        assert designer.get(100, "event", job.id) is None
    finally:
        await designer.close()


@pytest.mark.asyncio
async def test_shutdown_cancels_provider_and_clears_jobs():
    entered = asyncio.Event()

    async def generate(_):
        entered.set()
        await asyncio.Event().wait()

    designer = QrDesigner(provider=SimpleNamespace(generate=generate))
    job = designer.submit(100, "event", LINK, "Voxel blocks")
    await entered.wait()
    task = next(iter(designer.tasks))
    await designer.close()
    assert task.cancelled()
    assert not designer.jobs and not designer.enabled
    assert job.status == "failed" and not job.images
    await designer.close()


@pytest.mark.asyncio
async def test_validation_busy_and_provider_failure_do_not_leak_provider_details():
    gate = asyncio.Event()
    provider = SimpleNamespace(generate=lambda _: gate.wait())
    designer = QrDesigner(provider=provider)
    try:
        for prompt in (None, "", "  ", "x" * 1201, ["wrong"]):
            with pytest.raises(QrDesignError, match="1 to"):
                designer.submit(100, "event", LINK, prompt)
        designer.submit(100, "event", LINK, "One")
        designer.submit(200, "event", LINK, "Two")
        with pytest.raises(QrDesignError, match="busy"):
            designer.submit(300, "event", LINK, "Three")
    finally:
        await designer.close()
    broken = QrDesigner(
        provider=SimpleNamespace(
            generate=AsyncMock(side_effect=RuntimeError("secret-provider-response"))
        )
    )
    try:
        job = broken.submit(100, "event", LINK, "Test")
        await asyncio.gather(*broken.tasks)
        assert job.status == "failed" and "secret" not in job.error
        assert not job.images
    finally:
        await broken.close()


@pytest.mark.asyncio
async def test_job_cache_is_bounded_without_discarding_active_jobs(artwork):
    now = [0]
    designer = QrDesigner(
        provider=SimpleNamespace(generate=AsyncMock(return_value=artwork)), clock=lambda: now[0]
    )
    try:
        first = None
        for index in range(MAX_JOBS + 1):
            job = designer.submit(100, "event", LINK, "Blocks")
            first = first or job
            await asyncio.gather(*designer.tasks)
            now[0] += 31
        assert len(designer.jobs) == MAX_JOBS
        assert first.id not in designer.jobs
    finally:
        await designer.close()


@pytest.mark.asyncio
async def test_scan_work_does_not_block_async_updates(monkeypatch):
    entered, release = threading.Event(), threading.Event()

    def compose(*_, **__):
        entered.set()
        assert release.wait(timeout=2), "Image composition blocked the event loop"
        return {True: b"checked-png", False: b"checked-png"}

    monkeypatch.setattr("app.services.qr_designer.styled_qr_images", compose)
    designer = QrDesigner(provider=SimpleNamespace(generate=AsyncMock(return_value=b"artwork")))
    try:
        job = designer.submit(100, "event", LINK, "Blocks")
        async with asyncio.timeout(1):
            while not entered.is_set():
                await asyncio.sleep(0.01)
        assert job.status == "verifying" and not job.images
        # Other async work can still run while image composition is waiting.
        assert (
            await asyncio.wait_for(asyncio.sleep(0, result="responsive"), timeout=0.5)
            == "responsive"
        )
        release.set()
        await asyncio.gather(*designer.tasks)
        assert job.status == "ready"
    finally:
        release.set()
        await designer.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 401, 429, 500])
async def test_cloudflare_transport_uses_server_credentials_no_redirects_and_safe_errors(
    artwork, status
):
    encoded = base64.b64encode(artwork).decode()
    raw = json.dumps({"success": True, "result": {"image": encoded}}).encode()
    response = MagicMock(status=status)

    async def chunks(_):
        yield raw[:30]
        yield raw[30:]

    response.content.iter_chunked = chunks
    session = MagicMock()
    session.post.return_value.__aenter__ = AsyncMock(return_value=response)
    session.post.return_value.__aexit__ = AsyncMock(return_value=None)
    client = CloudflareImages(QrImageSettings("a" * 32, "test-secret"), session)
    if status == 200:
        assert await client.generate("Minecraft") == artwork
    else:
        with pytest.raises(QrDesignError) as error:
            await client.generate("Minecraft")
        assert "test-secret" not in str(error.value)
    assert session.post.call_count == 1
    options = session.post.call_args.kwargs
    assert options["headers"] == {"Authorization": "Bearer test-secret"}
    assert options["allow_redirects"] is False
    assert "Minecraft" in options["json"]["prompt"]


@pytest_asyncio.fixture
async def design_client(repository, artwork):
    for user_id in (100, 200):
        await complete_student_registration(
            repository,
            user_id,
            Student(str(user_id), "Student", f"{user_id}@example.test"),
            code="123456",
        )
    events = EventRepository(repository.db, clock=repository.clock)
    event = await events.create(100, "Voxel event")
    other = await events.create(200, "Other event")
    provider = SimpleNamespace(generate=AsyncMock(return_value=artwork))
    designer = QrDesigner(provider=provider)
    bot = SimpleNamespace(
        token=TOKEN, me=AsyncMock(return_value=SimpleNamespace(username="example_bot"))
    )
    async with TestClient(TestServer(create_web_app(events, bot, qr_designer=designer))) as client:
        client.event_id, client.other_id, client.designer = event.id, other.id, designer
        yield client


@pytest.mark.asyncio
async def test_design_endpoints_require_signed_identity_and_event_owner(design_client):
    client = design_client
    path = f"/api/events/{client.event_id}/qr/designs"
    assert (await client.post(path, json={"prompt": "Blocks"})).status == 401
    assert (await client.post(path, headers=headers(200), json={"prompt": "Blocks"})).status == 400
    assert not client.designer.jobs
    response = await client.post(path, headers=headers(), json={"prompt": "Blocks"})
    assert response.status == 202
    job_id = (await response.json())["id"]
    await asyncio.gather(*client.designer.tasks)
    for suffix in ("", "/image"):
        assert (await client.get(f"{path}/{job_id}{suffix}")).status == 401
        assert (await client.get(f"{path}/{job_id}{suffix}", headers=headers(200))).status == 400
        own_path = f"/api/events/{client.other_id}/qr/designs/{job_id}{suffix}"
        assert (await client.get(own_path, headers=headers(200))).status == 404
    response = await client.get(f"{path}/{job_id}", headers=headers())
    assert (await response.json())["status"] == "ready"
    for transparent in ("true", "false"):
        response = await client.get(
            f"{path}/{job_id}/image?transparent={transparent}", headers=headers()
        )
        assert response.status == 200 and response.headers["Cache-Control"] == "no-store"
        image = Image.open(BytesIO(await response.read()))
        assert scan_verified(image, f"https://t.me/example_bot?start=event_{client.event_id}")
        assert image.mode == ("RGBA" if transparent == "true" else "RGB")
    assert (
        await client.get(f"{path}/{job_id}/image?transparent=1", headers=headers())
    ).status == 400


@pytest.mark.asyncio
async def test_selected_design_survives_cache_expiry_and_application_restart(
    design_client, repository
):
    client = design_client
    path = f"/api/events/{client.event_id}/qr/designs"
    response = await client.post(path, headers=headers(), json={"prompt": "Illustrated autumn"})
    job_id = (await response.json())["id"]
    await asyncio.gather(*client.designer.tasks)
    expected = dict(client.designer.jobs[job_id].images)
    # An expired in-memory job cannot make the selected artwork disappear.
    client.designer.jobs.clear()
    state = await (await client.get(path, headers=headers())).json()
    assert state["selected"]["id"] == job_id and state["active"] is None
    await client.close()
    bot = SimpleNamespace(token=TOKEN)
    async with TestClient(
        TestServer(create_web_app(EventRepository(repository.db), bot))
    ) as reopened:
        # Persistence also works with AI credentials disabled, without generating again.
        state = await (await reopened.get(path, headers=headers())).json()
        assert state["selected"]["id"] == job_id and state["active"] is None
        assert (await reopened.get(f"{path}/{job_id}", headers=headers())).status == 200
        for transparent, png in expected.items():
            response = await reopened.get(
                f"{path}/{job_id}/image?transparent={str(transparent).lower()}", headers=headers()
            )
            assert response.status == 200 and await response.read() == png
        for method, suffix in (("GET", ""), ("DELETE", ""), ("GET", f"/{job_id}/image")):
            assert (await reopened.request(method, path + suffix)).status == 401
            assert (
                await reopened.request(method, path + suffix, headers=headers(200))
            ).status == 400


@pytest.mark.asyncio
async def test_failed_generation_or_save_keeps_selected_design(design_client, monkeypatch):
    client = design_client
    path = f"/api/events/{client.event_id}/qr/designs"
    first = await (await client.post(path, headers=headers(), json={"prompt": "Original"})).json()
    await asyncio.gather(*client.designer.tasks)
    original = dict(client.designer.jobs[first["id"]].images)
    clock = client.designer.clock
    client.designer.clock = lambda: clock() + 31
    monkeypatch.setattr(
        client.designer.store, "save", AsyncMock(side_effect=OSError("private detail"))
    )
    second = await (await client.post(path, headers=headers(), json={"prompt": "New"})).json()
    await asyncio.gather(*client.designer.tasks)
    failed = client.designer.jobs[second["id"]]
    assert failed.status == "failed" and not failed.images and "private detail" not in failed.error
    state = await (await client.get(path, headers=headers())).json()
    assert state["selected"]["id"] == first["id"] and state["active"] is None
    for transparent, png in original.items():
        assert (
            await client.designer.store.image(
                100, client.event_id, first["id"], transparent=transparent
            )
            == png
        )


@pytest.mark.asyncio
async def test_reset_cancels_pending_generation_and_persists_standard_choice(design_client):
    client = design_client
    path = f"/api/events/{client.event_id}/qr/designs"
    await client.post(path, headers=headers(), json={"prompt": "Original"})
    await asyncio.gather(*client.designer.tasks)
    clock = client.designer.clock
    client.designer.clock = lambda: clock() + 31
    entered = asyncio.Event()

    async def wait_for_image(_):
        entered.set()
        await asyncio.Event().wait()

    client.designer.provider.generate.side_effect = wait_for_image
    job = await (await client.post(path, headers=headers(), json={"prompt": "Replacement"})).json()
    await entered.wait()
    state = await (await client.get(path, headers=headers())).json()
    assert state["selected"] and state["active"]["id"] == job["id"]
    # Another organizer cannot cancel the owner's generation or reset its selection.
    assert (await client.delete(path, headers=headers(200))).status == 400
    assert client.designer.jobs[job["id"]].status == "generating"
    state = await (await client.delete(path, headers=headers())).json()
    assert state["selected"] is None and state["active"] is None
    assert state["retry_after"] > 0  # Reset cannot bypass generation rate limits.
    assert client.designer.jobs[job["id"]].task.cancelled()
    client.designer.jobs.clear()
    assert (await (await client.get(path, headers=headers())).json())["selected"] is None
    assert (await client.get(f"{path}/{job['id']}/image", headers=headers())).status == 404


@pytest.mark.asyncio
async def test_concurrent_design_replacement_keeps_both_backgrounds_atomic(design_client):
    client = design_client
    store = client.designer.store
    with pytest.raises(ValueError, match="Both"):
        await store.save(100, client.event_id, "invalid", {True: b"partial"})
    assert await store.selected(100, client.event_id) is None
    images = {
        "first": {True: b"first-transparent", False: b"first-opaque"},
        "second": {True: b"second-transparent", False: b"second-opaque"},
    }
    await asyncio.gather(
        *(store.save(100, client.event_id, name, pair) for name, pair in images.items())
    )
    selected = await store.selected(100, client.event_id)
    assert selected in images
    for transparent, png in images[selected].items():
        assert await store.image(100, client.event_id, selected, transparent=transparent) == png


@pytest.mark.asyncio
async def test_standard_qr_supports_both_backgrounds_and_rejects_invalid_flags(design_client):
    client = design_client
    path = f"/api/events/{client.event_id}/qr"
    for flag in ("true", "false"):
        response = await client.get(path + f"?transparent={flag}", headers=headers())
        assert response.status == 200
        image = Image.open(BytesIO(await response.read())).convert("RGBA")
        assert image.getpixel((0, 0))[3] == (0 if flag == "true" else 255)
    assert (await client.get(path + "?transparent=wrong", headers=headers())).status == 400


@pytest.mark.asyncio
async def test_pending_failed_and_expired_designs_never_download_unchecked_images(design_client):
    client = design_client
    gate = asyncio.Event()
    client.designer.provider = SimpleNamespace(generate=lambda _: gate.wait())
    path = f"/api/events/{client.event_id}/qr/designs"
    response = await client.post(path, headers=headers(), json={"prompt": "Blocks"})
    job_id = (await response.json())["id"]
    response = await client.post(path, headers=headers(), json={"prompt": "Changed prompt"})
    assert response.status == 202 and (await response.json())["id"] == job_id
    assert len(client.designer.jobs) == 1
    response = await client.get(f"{path}/{job_id}/image", headers=headers())
    assert response.status == 409
    response = await client.get(f"{path}/unknown/image", headers=headers())
    assert response.status == 404
    for payload in ({"prompt": ""}, {"prompt": ["wrong type"]}, []):
        response = await client.post(path, headers=headers(), json=payload)
        assert response.status == 400


@pytest.mark.asyncio
async def test_completed_job_returns_countdown_and_rate_limits_have_retry_after(design_client):
    client = design_client
    now = [0]
    client.designer.clock = lambda: now[0]
    path = f"/api/events/{client.event_id}/qr/designs"
    response = await client.post(path, headers=headers(), json={"prompt": "Autumn colors"})
    data = await response.json()
    assert data["elapsed_seconds"] == 0 and data["retry_after"] == 30
    await asyncio.gather(*client.designer.tasks)
    now[0] = 12
    response = await client.get(f"{path}/{data['id']}", headers=headers())
    data = await response.json()
    assert data["status"] == "ready" and data["retry_after"] == 18
    response = await client.post(path, headers=headers(), json={"prompt": "Winter colors"})
    assert response.status == 429 and response.headers["Retry-After"] == "18"
    assert (await response.json())["retry_after"] == 18
    assert len(client.designer.jobs) == 1
    now[0] = 30
    response = await client.post(path, headers=headers(), json={"prompt": "Winter colors"})
    assert response.status == 202 and len(client.designer.jobs) == 2


@pytest.mark.asyncio
async def test_active_design_for_another_event_does_not_replace_it():
    gate = asyncio.Event()
    designer = QrDesigner(provider=SimpleNamespace(generate=lambda _: gate.wait()))
    try:
        job = designer.submit(100, "first-event", LINK, "First design")
        with pytest.raises(QrDesignCooldown) as error:
            designer.submit(100, "second-event", LINK, "Second design")
        assert error.value.retry_after == 5
        assert designer.get(100, "first-event", job.id) is job
        assert len(designer.jobs) == 1
    finally:
        await designer.close()
