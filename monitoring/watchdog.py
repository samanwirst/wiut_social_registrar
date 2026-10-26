"""Independent ten-second supervisor. Run with a systemd EnvironmentFile, never a poller."""

import argparse
import fcntl
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from monitoring.alerts import deliver, observe
from monitoring.state import admin_ids, read_json, save_json
from monitoring.telegram import send_alert


def command(arguments, *, timeout=8):
    result = subprocess.run(arguments, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError("Supervisor command failed")
    return result.stdout


def health_url(url, *, ca_file=None):
    context = ssl.create_default_context()
    if ca_file:
        # A development CA augments the system roots; it must not replace them
        # when the same host also monitors a publicly trusted production URL.
        context.load_verify_locations(cafile=ca_file)
    with urllib.request.urlopen(url, context=context, timeout=4) as reply:
        return reply.status == 200 and json.loads(reply.read(16384)).get("status") in {
            "ok",
            "degraded",
        }


def certificate_hours(url, *, now):
    parsed = urlsplit(url)
    with socket.create_connection((parsed.hostname, parsed.port or 443), timeout=4) as raw:
        with ssl.create_default_context().wrap_socket(raw, server_hostname=parsed.hostname) as tls:
            return (ssl.cert_time_to_seconds(tls.getpeercert()["notAfter"]) - now) / 3600


def collect(args, previous, *, now):
    issues = {}
    metadata = {}
    can_repair = False
    if args.project:
        ids = command(
            ["docker", "ps", "-aq", "--filter", "label=com.docker.compose.project=" + args.project]
        ).split()
        containers = json.loads(command(["docker", "inspect", *ids])) if ids else []
        by_service = {
            item["Config"]["Labels"].get("com.docker.compose.service"): item for item in containers
        }
        for name in ("bot", "postgres", "caddy"):
            item = by_service.get(name)
            if not item or item["State"]["Status"] != "running":
                issues["process:" + name] = name + " is not running"
            elif name != "bot" and item["State"].get("Health", {}).get("Status") == "unhealthy":
                issues["process:" + name] = name + " is unhealthy"
        bot = by_service.get("bot")
        if bot:
            metadata["container"] = bot["Id"]
            metadata["restarts"] = bot["RestartCount"]
            can_repair = bot["State"]["Status"] == "running"
            started = (
                datetime.fromisoformat(bot["State"]["StartedAt"][:26].replace("Z", "+00:00"))
                .replace(tzinfo=timezone.utc)
                .timestamp()
            )
            if previous.get("container") == bot["Id"] and bot["RestartCount"] > previous.get(
                "restarts", 0
            ):
                issues["restart"] = "The bot restarted unexpectedly"
            if can_repair and now - started < 60:
                return issues, metadata, False
            # Legacy images have no runtime heartbeat. Read only fixed error markers,
            # never copy a raw log line, request, token or student record into alerts.
            logs = subprocess.run(
                ["docker", "logs", "--since", "30s", "--tail", "500", bot["Id"]],
                capture_output=True,
                text=True,
                timeout=8,
            )
            content = logs.stdout + logs.stderr
            if " ERROR " in content or "Traceback (most recent call last)" in content:
                issues["application"] = (
                    "The bot reported an application error; inspect private server logs"
                )
            if (
                "Registration email unavailable (" in content
                or "Verification email submission failed (" in content
                or "Verification email submission unconfirmed (" in content
            ):
                issues["email"] = "Verification email submission failed or could not be confirmed"
    elif args.user_service:
        properties = command(
            [
                "systemctl",
                "--user",
                "show",
                args.user_service,
                "-p",
                "ActiveState",
                "-p",
                "NRestarts",
            ]
        )
        values = dict(line.split("=", 1) for line in properties.splitlines() if "=" in line)
        can_repair = values.get("ActiveState") == "active"
        metadata["restarts"] = int(values.get("NRestarts", "0"))
        if metadata["restarts"] > previous.get("restarts", 0):
            issues["restart"] = "The bot service restarted unexpectedly"
        if not can_repair:
            issues["process:bot"] = "The bot service is not running"
    if args.url:
        try:
            if not health_url(
                args.url, ca_file=os.environ.get("REGISTRAR_MONITOR_CA_FILE") or None
            ):
                issues["http"] = "The bot health endpoint is unavailable"
        except Exception:
            issues["http"] = "The bot health endpoint is unavailable"
    runtime = read_json(args.env_dir / ".bot-health.json") if args.runtime else {}
    if runtime:
        if now - runtime.get("updated_at", 0) > 45 or runtime.get("phase") in {"failed", "stopped"}:
            issues["heartbeat"] = "The bot heartbeat has stopped"
        else:
            for component, status in runtime.get("components", {}).items():
                if (
                    component in {"database", "outlook", "polling", "cleanup", "broadcasts"}
                    and status.get("ok") is False
                ):
                    reason = status.get("reason", "unavailable")
                    if not re.fullmatch(r"[A-Za-z0-9 _:.\-/]{0,120}", reason):
                        reason = "unavailable"
                    issues[component] = component.capitalize() + ": " + reason
            polling = runtime.get("components", {}).get("polling")
            if polling and now - polling.get("checked_at", 0) > 120:
                issues["polling"] = "Telegram polling has stopped responding"
            elif not polling and now - runtime.get("started_at", 0) > 120:
                issues["polling"] = "Telegram polling did not start"
            for key, value in runtime.get("incidents", {}).items():
                if (
                    re.fullmatch(
                        r"(?:handler|background|fatal|miniapp|qr|email|broadcast):[A-Za-z0-9_]{1,80}",
                        key,
                    )
                    and now - value.get("at", 0) < 60
                ):
                    issues[key] = "Unexpected application error (" + key + ")"
    elif args.require_runtime or args.runtime and (args.env_dir / ".bot-health.json").exists():
        issues["heartbeat"] = "The bot runtime heartbeat is missing"
    if args.public_url:
        try:
            if not health_url(args.public_url):
                issues["public_https"] = "The public Mini App is unavailable"
            if certificate_hours(args.public_url, now=now) < 48:
                issues["tls"] = "The public HTTPS certificate expires in less than 48 hours"
        except Exception:
            issues["public_https"] = (
                "The public Mini App or its trusted HTTPS certificate is unavailable"
            )
    if args.backups:
        newest = max(
            (p.stat().st_mtime for p in args.backups.glob("*.dump") if p.stat().st_size), default=0
        )
        if now - newest > 30 * 3600:
            issues["backup"] = "No successful database backup in the last 30 hours"
        result = command(
            ["systemctl", "show", "wiut-social-registrar-backup.service", "-p", "Result", "--value"]
        ).strip()
        if result and result != "success":
            issues["backup"] = "The last database backup failed"
    if shutil.disk_usage(args.env_dir).free < 2 * 1024**3:
        issues["disk"] = "Less than 2 GiB of disk space remains"
    return issues, metadata, can_repair


def repair(args, state, issues, can_repair, *, now, persist=lambda: None):
    failure = "heartbeat" in issues or "http" in issues
    state["failed_checks"] = state.get("failed_checks", 0) + 1 if failure else 0
    attempts = [timestamp for timestamp in state.get("repairs", []) if now - timestamp < 3600]
    state["repairs"] = attempts
    if not args.repair or not can_repair or state["failed_checks"] < 3:
        return
    if len(attempts) >= 3 or attempts and now - attempts[-1] < 300:
        return
    if args.project:
        target = state.get("container", "")
        if not re.fullmatch(r"[a-f0-9]{64}", target):
            return
        arguments = ["docker", "restart", "--time", "60", target]
    elif args.user_service:
        arguments = ["systemctl", "--user", "restart", args.user_service]
    else:
        return
    # Persist before submitting: even a killed watchdog or an ambiguous timeout
    # consumes the restart budget, preventing a rapid restart loop.
    state["repairs"].append(now)
    persist()
    command(arguments, timeout=70)
    state["failed_checks"] = 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-dir", type=Path, required=True)
    parser.add_argument(
        "--url", default="", help="Liveness URL; omit when the Mini App is disabled"
    )
    parser.add_argument("--name", default="Production")
    parser.add_argument("--project", choices=["wiut-social-registrar-production"])
    parser.add_argument("--user-service", choices=["wiut-social-registrar.service"])
    parser.add_argument("--public-url", default="")
    parser.add_argument("--backups", type=Path)
    parser.add_argument("--state-name", default=".bot-watchdog.json")
    parser.add_argument("--runtime", action="store_true")
    parser.add_argument("--require-runtime", action="store_true")
    parser.add_argument("--repair", action="store_true")
    parser.add_argument("--test-alert", action="store_true")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"\.bot-watchdog[a-z0-9-]*\.json", args.state_name):
        parser.error("Invalid state filename")
    try:
        recipients = admin_ids(os.environ.get("BOT_ADMIN_IDS"))
    except ValueError as error:
        parser.error(str(error))
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not recipients or not token:
        print("Watchdog requires BOT_ADMIN_IDS and TELEGRAM_BOT_TOKEN")
        return 2
    path = args.env_dir / args.state_name
    lock_path = path.with_suffix(".lock")
    os.umask(0o077)
    with lock_path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        state = read_json(path)
        now = time.time()

        def send(recipient, text):
            return send_alert(
                token,
                recipient,
                text,
                address=os.environ.get("REGISTRAR_TELEGRAM_API_IPV4", ""),
                test_environment=os.environ.get("TELEGRAM_TEST_ENVIRONMENT", "false").lower()
                == "true",
            )

        if args.test_alert:
            results = [
                send(
                    recipient,
                    f"Social Registrar · {args.name}\nAdministrator monitoring is connected\nYou will receive confirmed outage alerts here",
                )
                for recipient in recipients
            ]
            print(
                "Administrator notification delivered"
                if all(results)
                else "Administrator notification could not be delivered"
            )
            return 0 if all(results) else 1
        try:
            issues, metadata, can_repair = collect(args, state, now=now)
            state.update(metadata)
            complete = True
        except Exception as error:
            issues, can_repair = (
                {"supervisor": "Monitoring probe failed (" + type(error).__name__ + ")"},
                False,
            )
            complete = False
        observe(state, issues, recipients, now=now, name=args.name, complete=complete)
        save_json(path, state)
        deliver(state, send, now=now)
        save_json(path, state)
        try:
            repair(args, state, issues, can_repair, now=now, persist=lambda: save_json(path, state))
        except Exception:
            # Never print a command's stdout/stderr or credential-bearing URLs.
            print("Automatic restart did not complete; operator alert remains active")
        save_json(path, state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
