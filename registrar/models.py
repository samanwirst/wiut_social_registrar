from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

EMAIL_PATTERN = re.compile(r"[\w.!#$%&'*+/=?^`{|}~-]+@[\w-]+(?:\.[\w-]+)+", re.UNICODE)


def validate_student_id(value: str) -> str:
    student_id = value.strip()
    if not re.fullmatch(r"[0-9]{1,32}", student_id):
        raise ValueError("Student ID must contain 1 to 32 digits. Leading zeroes are preserved.")
    return student_id


def validate_message(subject: str, body: str) -> None:
    if not subject.strip() or "\n" in subject or "\r" in subject:
        raise ValueError("Provide a non-empty email subject on a single line.")
    if not body.strip():
        raise ValueError("The email body must not be empty.")


@dataclass
class Student:
    student_id: str
    name: str
    email: str
    account: str = ""
    email_addresses: list[str] = field(default_factory=list)
    source: str = "microsoft_graph"

    def to_dict(self) -> dict:
        return asdict(self)

    def format(self) -> str:
        lines = [f"ID: {self.student_id}", f"Name: {self.name or 'not specified'}", f"Email: {self.email}"]
        if self.account:
            lines.append(f"Account: {self.account}")
        return "\n".join(lines)
