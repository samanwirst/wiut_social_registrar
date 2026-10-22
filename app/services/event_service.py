from io import BytesIO

import segno


def event_qr(link: str, *, transparent: bool = False) -> bytes:
    buffer = BytesIO()
    segno.make_qr(link, error="m").save(
        buffer, kind="png", scale=8, border=4, light=None if transparent else "white"
    )
    return buffer.getvalue()
