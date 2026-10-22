"""Shared synthetic setup for scenarios that start after student verification."""

import hashlib
import hmac
import json
from datetime import datetime, timezone
from urllib.parse import urlencode

TEST_TOKEN = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789"


async def complete_student_registration(
    repository, user_id, student, *, education_level="CIFS", code="001234"
):
    await repository.reserve_code(user_id, student, code)
    await repository.consume_code(user_id, code)
    await repository.save_contact(user_id, user_id, "+998901234567")
    await repository.complete_registration(user_id, education_level)


def signed_init_data(user_id=100, *, token=TEST_TOKEN, age=0, **extra):
    values = {
        "auth_date": str(int(datetime.now(timezone.utc).timestamp()) - age),
        "user": json.dumps({"id": user_id, "first_name": "Student", "is_bot": False}),
        **extra,
    }
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    signature = hmac.new(
        secret,
        "\n".join(f"{key}={value}" for key, value in sorted(values.items())).encode(),
        hashlib.sha256,
    ).hexdigest()
    return urlencode({**values, "hash": signature})
