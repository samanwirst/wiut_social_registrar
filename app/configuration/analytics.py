from dataclasses import dataclass, field

from app.analytics.auth import valid_password_hash
from registrar.config import ConfigurationError


@dataclass(frozen=True)
class AnalyticsSettings:
    password_hash: str = field(default="", repr=False)
    retention_days: int = 90

    @classmethod
    def load(cls, values):
        password = str(values.get("ANALYTICS_ADMIN_PASSWORD_HASH") or "").strip()
        if password and not valid_password_hash(password):
            raise ConfigurationError(
                "Generate ANALYTICS_ADMIN_PASSWORD_HASH with python -m app.analytics.setup"
            )
        try:
            retention = int(values.get("ANALYTICS_RETENTION_DAYS") or 90)
            if not 30 <= retention <= 365:
                raise ValueError
        except (TypeError, ValueError):
            raise ConfigurationError(
                "ANALYTICS_RETENTION_DAYS must be between 30 and 365"
            ) from None
        return cls(password, retention)
