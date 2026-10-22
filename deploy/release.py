#!/usr/bin/env python3
"""Fixed-command SSH entry point: deploy only this project's immutable image."""

import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path("/opt/wiut-social-registrar")
PROJECT = "wiut-social-registrar-production"
IMAGE = "ghcr.io/samanwirst/wiut_social_registrar"


def manifest(stream):
    raw = stream.read(16385)
    if len(raw) > 16384:
        raise ValueError("Oversized deployment manifest")
    data = json.loads(raw)
    if set(data) != {"image", "commit", "registry_user", "registry_token"}:
        raise ValueError("Invalid deployment manifest")
    if not isinstance(data["image"], str) or not re.fullmatch(
        re.escape(IMAGE) + r"@sha256:[a-f0-9]{64}", data["image"]
    ):
        raise ValueError("Invalid release image")
    if not isinstance(data["commit"], str) or not re.fullmatch(r"[a-f0-9]{40}", data["commit"]):
        raise ValueError("Invalid release commit")
    if not isinstance(data["registry_user"], str) or not re.fullmatch(
        r"[a-zA-Z0-9_-]{1,100}", data["registry_user"]
    ):
        raise ValueError("Invalid registry identity")
    if not isinstance(data["registry_token"], str) or not 1 <= len(data["registry_token"]) <= 8192:
        raise ValueError("Invalid registry credential")
    return data


def run(args, *, env, input=None, timeout=300):
    result = subprocess.run(
        args, input=input, env=env, capture_output=True, text=True, timeout=timeout
    )
    if result.returncode:
        # Docker and application errors can contain credentials; keep them off CI logs.
        raise RuntimeError("A deployment command failed")
    return result.stdout


def compose_command(*args):
    return [
        "docker",
        "compose",
        "--project-name",
        PROJECT,
        "--project-directory",
        str(ROOT),
        "--env-file",
        str(ROOT / ".local/.env"),
        "-f",
        str(ROOT / "compose.yaml"),
        "-f",
        str(ROOT / "compose.production.yaml"),
        "-f",
        str(ROOT / "compose.release.yaml"),
        *args,
    ]


def compose(*args, env, timeout=300):
    return run(compose_command(*args), env=env, timeout=timeout)


def bootstrap_database(env):
    shared = ROOT / "shared"
    completed = shared / "initial-import.complete"
    if completed.exists() or (shared / "current.json").exists():
        return
    snapshot = shared / "initial-snapshot.json"
    if not snapshot.is_file():
        raise RuntimeError("The private initial database snapshot is missing")
    compose(
        "run",
        "--rm",
        "--no-deps",
        "-T",
        "--pull",
        "never",
        "-v",
        str(snapshot) + ":/migration/snapshot.json:ro",
        "bot",
        "python",
        "-m",
        "scripts.transfer_database",
        "import",
        "--env-file",
        "/config/.env",
        "--file",
        "/migration/snapshot.json",
        env=env,
    )
    completed.touch(mode=0o600)


def backup_database(env):
    folder = ROOT / "shared/backups"
    folder.mkdir(mode=0o700, exist_ok=True)
    destination = folder / (str(time.time_ns()) + ".dump")
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        result = subprocess.run(
            compose_command(
                "exec",
                "-T",
                "postgres",
                "pg_dump",
                "-U",
                "registrar",
                "-d",
                "registrar",
                "--format=custom",
            ),
            stdout=output,
            stderr=subprocess.PIPE,
            env=env,
            timeout=180,
        )
    if result.returncode:
        destination.unlink()
        raise RuntimeError("Database backup failed")
    for old in sorted(folder.glob("*.dump"), key=lambda path: path.stat().st_mtime, reverse=True)[
        14:
    ]:
        old.unlink()


def wait_healthy(env, *, timeout=150):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        container = compose("ps", "-q", "bot", env=env).strip()
        if container:
            state = run(
                ["docker", "inspect", "--format", "{{.State.Health.Status}}", container], env=env
            ).strip()
            if state == "healthy":
                with urllib.request.urlopen("http://127.0.0.1:18080/health", timeout=5) as reply:
                    if reply.status == 200:
                        return
            if state == "unhealthy":
                break
        time.sleep(2)
    raise RuntimeError("The release did not become healthy")


def deploy(data):
    shared = ROOT / "shared"
    if not (shared / "ready").is_file():
        raise RuntimeError("Production bootstrap is incomplete")
    with (shared / "deploy.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        current = shared / "current.json"
        previous = json.loads(current.read_text()) if current.exists() else None
        with tempfile.TemporaryDirectory(prefix="registry-", dir=shared) as auth:
            env = {**os.environ, "DOCKER_CONFIG": auth, "REGISTRAR_IMAGE": data["image"]}
            run(
                [
                    "docker",
                    "login",
                    "ghcr.io",
                    "--username",
                    data["registry_user"],
                    "--password-stdin",
                ],
                env=env,
                input=data["registry_token"],
            )
            compose("config", "--quiet", env=env)
            compose("pull", "bot", env=env, timeout=600)
            bootstrap_database(env)
            backup_database(env)
            # Database files and TLS volumes belong to this project and are never recreated here.
            try:
                compose("up", "-d", "--no-deps", "--no-build", "bot", env=env)
                wait_healthy(env)
            except Exception:
                if previous:
                    rollback = {**env, "REGISTRAR_IMAGE": previous["image"]}
                    compose("up", "-d", "--no-deps", "--no-build", "bot", env=rollback)
                    wait_healthy(rollback)
                raise
            record = {key: data[key] for key in ("image", "commit")}
            record["deployed_at"] = int(time.time())
            temporary = shared / "current.json.tmp"
            temporary.write_text(json.dumps(record) + "\n")
            temporary.chmod(0o600)
            temporary.replace(current)
            print("Production release is healthy: " + data["commit"][:12], flush=True)


def main():
    os.umask(0o077)
    try:
        if sys.argv[1:] == ["--backup"]:
            shared = ROOT / "shared"
            with (shared / "deploy.lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                current = json.loads((shared / "current.json").read_text())
                backup_database({**os.environ, "REGISTRAR_IMAGE": current["image"]})
            print("Private production database backup completed")
        elif sys.argv[1:]:
            raise ValueError("Unsupported deployment arguments")
        else:
            deploy(manifest(sys.stdin))
        return 0
    except Exception as error:
        print("Production deployment failed (" + type(error).__name__ + ")", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
