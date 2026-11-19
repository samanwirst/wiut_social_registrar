"""Interactive password setup without putting the password in shell arguments/history."""

import argparse
from getpass import getpass
from pathlib import Path

from app.analytics.auth import hash_password
from registrar.environment import save_environment_value


def main():
    parser = argparse.ArgumentParser(description="Set the analytics website password")
    parser.add_argument("--env-file", type=Path, required=True)
    args = parser.parse_args()
    password = getpass("Analytics password (at least 12 characters): ")
    if password != getpass("Confirm password: "):
        parser.error("Passwords do not match")
    try:
        encoded = hash_password(password)
    except ValueError as error:
        parser.error(str(error))
    save_environment_value(args.env_file.resolve(), "ANALYTICS_ADMIN_PASSWORD_HASH", encoded)
    print("Password hash saved privately. Restart the bot, then open /admin on its HTTPS origin.")


if __name__ == "__main__":
    main()
