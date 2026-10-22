"""UTC clock shared by persistence and authentication; callers may inject a clock."""

from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
