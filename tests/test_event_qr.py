from struct import unpack_from

import pytest

from app.services.event_service import event_qr


@pytest.mark.parametrize("transparent", [False, True])
def test_event_png_preserves_opaque_chat_preview_and_exports_real_transparency(transparent):
    png = event_qr("https://t.me/example_bot?start=event_12345678-1234-4234-8234-123456789abc", transparent=transparent)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    chunks, position = {}, 8
    while position < len(png):
        size = unpack_from(">I", png, position)[0]
        chunks[png[position + 4:position + 8]] = png[position + 8:position + 8 + size]
        position += size + 12
    width, height, _, color_type, *_ = unpack_from(">IIBBBBB", chunks[b"IHDR"])
    assert width == height and width >= 256
    assert (b"tRNS" in chunks or color_type in {4, 6}) is transparent


def test_chat_qr_defaults_to_an_opaque_image():
    link = "https://t.me/example_bot?start=event_12345678-1234-4234-8234-123456789abc"
    assert event_qr(link) == event_qr(link, transparent=False)
