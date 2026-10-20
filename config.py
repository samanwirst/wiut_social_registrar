from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from aiogram.utils.token import TokenValidationError, validate_token
from dotenv import dotenv_values

from registrar.config import ConfigurationError, Settings


@dataclass(frozen=True)
class BotSettings:
    token: str = field(repr=False)
    graph: Settings = field(repr=False)

    @classmethod
    def load(cls, env_file: Path | None = None) -> BotSettings:
        graph = Settings.load(env_file)
        values = {**dotenv_values(graph.env_file, interpolate=False), **os.environ}
        token = str(values.get("TELEGRAM_BOT_TOKEN") or "").strip()
        try:
            validate_token(token)
        except TokenValidationError:
            raise ConfigurationError("Set a valid TELEGRAM_BOT_TOKEN in .env.") from None
        return cls(token=token, graph=graph)
