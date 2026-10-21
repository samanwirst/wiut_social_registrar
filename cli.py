from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from registrar.config import ConfigurationError, Settings
from registrar.errors import GraphError
from registrar.graph import GraphClient
from registrar.models import validate_message, validate_student_id


def parse_args(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(
        description="Look up student profiles and send email from your account through Microsoft Graph."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--id", metavar="STUDENT_ID", help="Look up one student ID, preserving leading zeroes."
    )
    mode.add_argument(
        "--login",
        action="store_true",
        help="Sign in to Microsoft again and save the token cache in .env.",
    )
    mode.add_argument(
        "--logout", action="store_true", help="Remove the saved token cache from .env."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output the --id result as JSON; status messages go to stderr.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Show request methods, HTTP status codes, timings, and cache hits.",
    )
    parser.add_argument(
        "--env-file", type=Path, help="Path to .env (defaults to the directory containing cli.py)."
    )
    parser.add_argument(
        "--subject", help="Email subject. Only a preview is shown unless --send is provided."
    )
    body_input = parser.add_mutually_exclusive_group()
    body_input.add_argument("--body", help="Email body text.")
    body_input.add_argument(
        "--body-file", type=Path, help="UTF-8 file containing the email body text."
    )
    parser.add_argument(
        "--send", action="store_true", help="Send the email to the student from your account."
    )
    args = parser.parse_args(argv)
    if args.json and args.id is None:
        parser.error("--json requires --id")
    has_message = (
        args.subject is not None or args.body is not None or args.body_file is not None or args.send
    )
    if has_message and (
        args.id is None or args.subject is None or (args.body is None and args.body_file is None)
    ):
        parser.error("email requires --id, --subject, and either --body or --body-file")
    return args, has_message


def lookup_once(client, args, *, has_message: bool, body: str | None) -> int:
    student = client.find_student(args.id, refresh=args.send)
    result = student.to_dict() if student else None
    message = None
    if student and has_message:
        message = client.mail_preview(student, args.subject, body)
        if args.send:
            client.send_email(student, args.subject, body)
        message["status"] = "accepted" if args.send else "preview"
        result["message"] = message
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(student.format() if student else "No student found with this ID.")
        if message:
            print(
                f"\nFrom: {message['from']}\nTo: {message['to']}\nSubject: {message['subject']}\n\n{message['body']}"
            )
            print(
                "\nMicrosoft accepted the email for sending."
                if args.send
                else "\nPreview only. Add --send to send the email."
            )
    return 0 if student else 1


def interactive_lookup(client) -> None:
    print("Enter a student ID. Leave blank to exit.")
    while True:
        try:
            student_id = input("\nStudent ID: ").strip()
        except EOFError:
            break
        if not student_id:
            break
        try:
            student = client.find_student(validate_student_id(student_id))
            print(student.format() if student else "No student found with this ID.")
        except ConfigurationError:
            raise
        except (ValueError, GraphError) as error:
            print(str(error), file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args, has_message = parse_args(argv)
    try:
        if args.id is not None:
            args.id = validate_student_id(args.id)
        body = (
            args.body_file.read_text(encoding="utf-8") if args.body_file is not None else args.body
        )
        if has_message:
            validate_message(args.subject, body)
        settings = Settings.load(args.env_file)
        diagnostic_logger = logging.getLogger("registrar")
        diagnostic_logger.setLevel(
            logging.DEBUG if args.debug or settings.debug else logging.WARNING
        )
        diagnostic_logger.propagate = False
        if not diagnostic_logger.handlers:
            handler = logging.StreamHandler(sys.stderr)
            handler.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
            )
            diagnostic_logger.addHandler(handler)
        if args.logout:
            settings.save_cache(None)
            print("Local token cache removed from .env.")
            return 0
        with GraphClient(
            settings, status=lambda message: print(message, file=sys.stderr)
        ) as client:
            if args.login:
                profile = client.login(force=True)
                print(f"Signed in as {profile.get('mail') or profile['userPrincipalName']}.")
                return 0
            if args.id is not None:
                return lookup_once(client, args, has_message=has_message, body=body)
            interactive_lookup(client)
        return 0
    except KeyboardInterrupt:
        return 130
    except (ConfigurationError, GraphError, ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
