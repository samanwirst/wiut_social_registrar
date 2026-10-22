from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from registrar.config import ConfigurationError


@dataclass(frozen=True)
class MiniAppConfiguration:
    url: str
    host: str
    port: int
    cert_file: Path | None
    key_file: Path | None


def load_mini_app(values, env_file: Path, telegram_test: bool) -> MiniAppConfiguration:
    mini_app_url = str(values.get("MINI_APP_URL") or "").strip().rstrip("/")
    if mini_app_url:
        try:
            parsed = urlsplit(mini_app_url)
            allowed_schemes = {"https", "http"} if telegram_test else {"https"}
            if (
                parsed.scheme not in allowed_schemes
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.path
                or parsed.query
                or parsed.fragment
                or parsed.port == 0
            ):
                raise ValueError
        except ValueError:
            raise ConfigurationError(
                "MINI_APP_URL must be an HTTPS origin. HTTP is allowed only with TELEGRAM_TEST_ENVIRONMENT=true."
            ) from None
    cert_value = str(values.get("MINI_APP_TLS_CERT_FILE") or "").strip()
    key_value = str(values.get("MINI_APP_TLS_KEY_FILE") or "").strip()
    if bool(cert_value) != bool(key_value):
        raise ConfigurationError(
            "Set both MINI_APP_TLS_CERT_FILE and MINI_APP_TLS_KEY_FILE, or leave both empty."
        )
    if cert_value and (not mini_app_url or urlsplit(mini_app_url).scheme != "https"):
        raise ConfigurationError("Direct TLS requires an HTTPS MINI_APP_URL.")
    cert_file = (env_file.parent / cert_value).resolve() if cert_value else None
    key_file = (env_file.parent / key_value).resolve() if key_value else None
    try:
        mini_app_port = int(values.get("MINI_APP_PORT") or "8080")
        if not 1 <= mini_app_port <= 65535:
            raise ValueError
    except ValueError:
        raise ConfigurationError("MINI_APP_PORT must be a valid port number.") from None
    return MiniAppConfiguration(
        mini_app_url,
        str(values.get("MINI_APP_HOST") or "127.0.0.1").strip(),
        mini_app_port,
        cert_file,
        key_file,
    )
