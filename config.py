from __future__ import annotations

import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from aiogram.utils.token import TokenValidationError, validate_token

from app.configuration.database import load_database_url
from app.configuration.miniapp import load_mini_app
from app.configuration.qr_images import QrImageSettings
from monitoring.state import admin_ids
from registrar.config import ConfigurationError, Settings
from registrar.environment import read_environment, save_environment_value


@dataclass(frozen=True)
class BotSettings:
    token: str = field(repr=False)
    graph: Settings = field(repr=False)
    database_url: str = field(default="", repr=False)
    verification_secret: str = field(default="", repr=False)
    environment: str = "local"
    mini_app_url: str = ""
    mini_app_host: str = "127.0.0.1"
    mini_app_port: int = 8080
    telegram_test_environment: bool = False
    mini_app_tls_cert_file: Path | None = None
    mini_app_tls_key_file: Path | None = None
    qr_images: QrImageSettings = field(default_factory=QrImageSettings, repr=False)
    admin_ids: tuple[int, ...] = ()

    @classmethod
    def load(cls, env_file: Path | None = None) -> BotSettings:
        graph = Settings.load(env_file)
        values = read_environment(graph.env_file)
        token = str(values.get("TELEGRAM_BOT_TOKEN") or "").strip()
        try:
            validate_token(token)
        except TokenValidationError:
            raise ConfigurationError("Set a valid TELEGRAM_BOT_TOKEN in .env.") from None
        environment = str(values.get("APP_ENV") or "local").strip().lower()
        if environment not in {"local", "production"}:
            raise ConfigurationError("APP_ENV must be local or production.")
        telegram_test = str(values.get("TELEGRAM_TEST_ENVIRONMENT") or "false").strip().lower()
        if telegram_test not in {"true", "false"}:
            raise ConfigurationError("TELEGRAM_TEST_ENVIRONMENT must be true or false.")
        telegram_test = telegram_test == "true"
        if telegram_test and environment != "local":
            raise ConfigurationError(
                "TELEGRAM_TEST_ENVIRONMENT is available only with APP_ENV=local."
            )
        database_url = load_database_url(values, graph.env_file, environment, telegram_test)
        secret = str(values.get("BOT_VERIFICATION_SECRET") or "").strip()
        if not secret:
            secret = secrets.token_hex(32)
            save_environment_value(graph.env_file, "BOT_VERIFICATION_SECRET", secret)
        if not re.fullmatch(r"[0-9a-fA-F]{64}", secret):
            raise ConfigurationError(
                "BOT_VERIFICATION_SECRET must contain 64 hexadecimal characters."
            )
        mini = load_mini_app(values, graph.env_file, telegram_test)
        try:
            administrators = admin_ids(values.get("BOT_ADMIN_IDS"))
        except ValueError as error:
            raise ConfigurationError(str(error)) from None
        return cls(
            token=token,
            graph=graph,
            database_url=database_url,
            verification_secret=secret,
            environment=environment,
            mini_app_url=mini.url,
            mini_app_host=mini.host,
            mini_app_port=mini.port,
            telegram_test_environment=telegram_test,
            mini_app_tls_cert_file=mini.cert_file,
            mini_app_tls_key_file=mini.key_file,
            qr_images=QrImageSettings.load(values),
            admin_ids=administrators,
        )
