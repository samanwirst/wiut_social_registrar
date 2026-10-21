"""Read private configuration and persist renewable credentials in one place."""

import os
from pathlib import Path

from dotenv import dotenv_values, set_key


def read_environment(path: Path) -> dict[str, str | None]:
    return {**dotenv_values(path, interpolate=False), **os.environ}


def save_environment_value(path: Path, key: str, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    os.close(descriptor)
    path.chmod(0o600)
    set_key(path, key, value)
    path.chmod(0o600)
