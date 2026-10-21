"""Run pytest on disposable PostgreSQL and SQLite without loading runtime configuration."""

import json
import os
import secrets
import subprocess
import sys
import time
from uuid import uuid4


def main() -> int:
    container = "wiut-registrar-test-" + uuid4().hex[:12]
    password = secrets.token_hex(24)
    database = "registrar_test"
    started = False
    try:
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "-d",
                "--name",
                container,
                "--env",
                "POSTGRES_USER=registrar",
                "--env",
                f"POSTGRES_DB={database}",
                "--env",
                "POSTGRES_PASSWORD",
                "--publish",
                "127.0.0.1::5432",
                "--tmpfs",
                "/var/lib/postgresql/data:rw,nosuid",
                "postgres:17-alpine",
            ],
            env={**os.environ, "POSTGRES_PASSWORD": password},
            capture_output=True,
            text=True,
        )
        if result.returncode:
            print(
                "Could not start the temporary PostgreSQL container. Check Docker availability.",
                file=sys.stderr,
            )
            return result.returncode
        started = True
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            result = subprocess.run(
                [
                    "docker",
                    "exec",
                    container,
                    "pg_isready",
                    "-h",
                    "127.0.0.1",
                    "-U",
                    "registrar",
                    "-d",
                    database,
                ],
                capture_output=True,
            )
            if result.returncode == 0:
                break
            time.sleep(0.25)
        else:
            print("Temporary PostgreSQL did not become ready within 30 seconds.", file=sys.stderr)
            return 1
        mapping = json.loads(
            subprocess.check_output(
                [
                    "docker",
                    "inspect",
                    "--format",
                    "{{json .NetworkSettings.Ports}}",
                    container,
                ]
            )
        )
        port = mapping["5432/tcp"][0]["HostPort"]
        env = {
            **os.environ,
            "TEST_DATABASE_URL": f"postgresql+asyncpg://registrar:{password}@127.0.0.1:{port}/{database}",
        }
        print(
            "Testing SQLite and isolated PostgreSQL 17; runtime configuration is not used.",
            flush=True,
        )
        return subprocess.run(
            [sys.executable, "-m", "pytest", "-q", *sys.argv[1:]], env=env
        ).returncode
    except (OSError, subprocess.SubprocessError, ValueError, KeyError):
        print("Could not prepare or run the isolated database checks.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    finally:
        if started:
            subprocess.run(
                ["docker", "rm", "-f", container],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print("Temporary PostgreSQL container and data removed.", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
