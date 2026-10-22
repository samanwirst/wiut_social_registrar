"""Bounded, versioned form definitions and answers shared by both database backends."""

import math
from uuid import UUID

from app.event_errors import EventError

QUESTION_TYPES = {"text", "number", "single_choice", "multiple_choice"}


def apply_question_response(question, previous, *, text=None, action=None, option=None):
    """Return a new answer set and whether to advance; no persistence or chat I/O."""
    key, kind = question["id"], question["type"]
    answers = dict(previous)
    if action in {"choose", "toggle"}:
        if (
            kind not in {"single_choice", "multiple_choice"}
            or type(option) is not int
            or not 0 <= option < len(question["options"])
            or (action == "choose") != (kind == "single_choice")
        ):
            raise EventError("Choose a valid option using the latest buttons.")
        value = question["options"][option]
        if kind == "multiple_choice":
            values = list(answers.get(key, []))
            if value in values:
                values.remove(value)
            else:
                values.append(value)
            answers[key] = values
            return answers, False
        answers[key] = value
    elif action == "next" and kind == "multiple_choice":
        pass
    elif action == "skip" and not question["required"]:
        answers.pop(key, None)
    elif text is not None and kind in {"text", "number"}:
        answers[key] = text.strip()
    else:
        raise EventError("Use the inline buttons to answer this question.")
    validate_answers([question], {key: answers.get(key)})
    return answers, True


def validate_questions(questions):
    if not isinstance(questions, list) or len(questions) > 20:
        raise EventError("Use at most 20 questions per event.")
    result, seen = [], set()
    for item in questions:
        if not isinstance(item, dict):
            raise EventError("Each question must be an object.")
        try:
            question_id = str(UUID(item.get("id", "")))
        except (ValueError, TypeError, AttributeError):
            raise EventError("Each question needs a valid unique ID.") from None
        label, kind, required = item.get("label"), item.get("type"), item.get("required")
        if question_id in seen or not isinstance(label, str) or not 1 <= len(label.strip()) <= 200:
            raise EventError("Use unique question IDs and labels of 1 to 200 characters.")
        if (
            not isinstance(kind, str)
            or kind not in QUESTION_TYPES
            or not isinstance(required, bool)
        ):
            raise EventError("Choose a supported question type and whether it is required.")
        options = item.get("options", [])
        if kind in {"single_choice", "multiple_choice"}:
            if (
                not isinstance(options, list)
                or not 2 <= len(options) <= 20
                or any(
                    not isinstance(value, str) or not 1 <= len(value.strip()) <= 100
                    for value in options
                )
            ):
                raise EventError("Choice questions need 2 to 20 options of 1 to 100 characters.")
            options = [value.strip() for value in options]
            if len(set(options)) != len(options):
                raise EventError("Choice options must be unique.")
        else:
            options = []
        seen.add(question_id)
        result.append(
            {
                "id": question_id,
                "label": label.strip(),
                "type": kind,
                "required": required,
                "options": options,
            }
        )
    return result


def validate_answers(questions, answers):
    if not isinstance(answers, dict) or set(answers) - {item["id"] for item in questions}:
        raise EventError("Submit answers only for this event's questions.")
    result = {}
    for question in questions:
        key, kind = question["id"], question["type"]
        value = answers.get(key)
        if value is None or value == "" or value == []:
            if question["required"]:
                raise EventError(f"Please answer: {question['label']}")
            continue
        if kind == "multiple_choice":
            if (
                not isinstance(value, list)
                or len(value) > len(question["options"])
                or any(
                    not isinstance(item, str) or item not in question["options"] for item in value
                )
                or len(set(value)) != len(value)
            ):
                raise EventError(f"Select valid options for: {question['label']}")
        else:
            if not isinstance(value, str) or not 1 <= len(value.strip()) <= 2000:
                raise EventError(f"Use 1 to 2000 characters for: {question['label']}")
            value = value.strip()
            if kind == "single_choice" and value not in question["options"]:
                raise EventError(f"Select a valid option for: {question['label']}")
            if kind == "number":
                try:
                    if len(value) > 64 or not math.isfinite(float(value)):
                        raise ValueError
                except ValueError:
                    raise EventError(f"Enter a finite number for: {question['label']}") from None
        result[key] = value
    return result
