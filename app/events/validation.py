"""Normalize event editor input before entering a database transaction."""

from dataclasses import dataclass

from app.event_errors import EventError
from app.event_forms import validate_questions


def event_title(value: str) -> str:
    if not isinstance(value, str) or not 1 <= len(" ".join(value.split())) <= 200:
        raise EventError("Event names must contain 1 to 200 characters.")
    return " ".join(value.split())


@dataclass(frozen=True)
class EventChanges:
    title: str
    description: str
    registration_open: bool
    response_retention_days: int
    questions: list[dict]
    revision: int

    @classmethod
    def parse(cls, data):
        if not isinstance(data, dict) or set(data) != {
            "title",
            "description",
            "registration_open",
            "response_retention_days",
            "questions",
            "revision",
        }:
            raise EventError(
                "Submit the event title, description, status, retention, questions, and revision."
            )
        title = event_title(data["title"])
        description = data["description"]
        if not isinstance(description, str) or len(description) > 4000:
            raise EventError("Use at most 4000 characters for the description.")
        retention = data["response_retention_days"]
        if type(retention) is not int or not 1 <= retention <= 90:
            raise EventError("Keep answers for 1 to 90 days.")
        if not isinstance(data["registration_open"], bool) or type(data["revision"]) is not int:
            raise EventError("Supply a valid registration status and revision.")
        return cls(
            title,
            description.strip(),
            data["registration_open"],
            retention,
            validate_questions(data["questions"]),
            data["revision"],
        )
