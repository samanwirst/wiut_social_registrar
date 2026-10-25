"""Ordinary Telegram message entities: readable text with literal, untrusted values."""

from aiogram.utils.formatting import Bold, Code, Text

from registrar.models import Student


def error_text(error: Exception) -> str:
    return str(error).removesuffix(".")


def card(title: str, body: str | Text) -> Text:
    return Text(Bold(title), "\n\n", body)


def recipient_count(count: int) -> str:
    return f"{count} recipient" if count == 1 else f"{count} recipients"


def student_profile(
    student: Student, *, title="Your verified profile", education_level=None
) -> Text:
    content = Text(
        Bold(title),
        "\n\n",
        "ID: ",
        Code(student.student_id),
        "\n",
        "Name: ",
        student.name or "Not specified",
        "\n",
        "Email: ",
        student.email,
    )
    if student.account:
        content += Text("\nAccount: ", Code(student.account))
    if education_level:
        content += Text("\nEducation level: ", education_level)
    return content


def event_confirmation(event, *, already=False) -> Text:
    prefix = (
        "Your response has already been submitted for: "
        if already
        else "Your response has been submitted for: "
    )
    return Text(prefix, Bold(event.title))
