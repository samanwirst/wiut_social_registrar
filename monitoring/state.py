"""Private, atomic operational state; never student data or credentials."""

import json
import os
import tempfile
from pathlib import Path


def admin_ids(raw):
    try:
        values = json.loads(raw or "[]")
        if not isinstance(values, list) or len(values) > 20:
            raise ValueError
        if any(type(value) is not int or not 0 < value < 2**63 for value in values):
            raise ValueError
        return tuple(dict.fromkeys(values))
    except (ValueError, TypeError):
        raise ValueError("BOT_ADMIN_IDS must be a JSON array of positive Telegram IDs") from None


def read_json(path):
    try:
        path = Path(path)
        if path.stat().st_size > 256 * 1024:
            return {}
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix="." + path.name, dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(data, stream, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
