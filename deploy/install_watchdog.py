"""Install only this project's independent monitor; never deploy or start bot polling."""

import argparse
import os
import shutil
import subprocess
from pathlib import Path

PRODUCTION_ROOT = Path("/opt/wiut-social-registrar")
SERVICE = "wiut-social-registrar-watchdog"


def unit_argument(value):
    value = str(value)
    if any(character in value for character in "\r\n\0"):
        raise ValueError("Invalid systemd argument")
    return (
        '"'
        + value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("$", "$$")
        + '"'
    )


def units(mode, root, env_file, url, public_url=""):
    production = mode == "production"
    if production and (root != PRODUCTION_ROOT or env_file != root / ".local/.env"):
        raise ValueError("Production monitoring is restricted to /opt/wiut-social-registrar")
    directory = root / "operations" if production else root
    python = Path("/usr/bin/python3") if production else root / ".venv/bin/python"
    name = SERVICE + ("-external" if mode == "external" else "")
    args = [
        str(python),
        "-m",
        "monitoring.watchdog",
        "--env-dir",
        str(env_file.parent),
        "--name",
        {"production": "Production", "dev": "Dev", "external": "Production (external)"}[mode],
    ]
    if url:
        args += ["--url", url]
    if public_url:
        args += ["--public-url", public_url]
    if production:
        args += [
            "--project",
            "wiut-social-registrar-production",
            "--backups",
            str(root / "shared/backups"),
            "--runtime",
            "--repair",
        ]
    elif mode == "dev":
        args += [
            "--user-service",
            "wiut-social-registrar.service",
            "--runtime",
            "--require-runtime",
            "--repair",
        ]
    else:
        args += ["--state-name", ".bot-watchdog-production-external.json"]
    hardening = (
        f"""ProtectSystem=strict
ProtectHome=true
ReadWritePaths={unit_argument(env_file.parent)}
PrivateTmp=true
NoNewPrivileges=true
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
"""
        if production
        else ""
    )
    network = "After=network-online.target\nWants=network-online.target" if production else ""
    service = f"""[Unit]
Description=WIUT Social Registrar independent monitor ({mode})
{network}

[Service]
Type=oneshot
WorkingDirectory={str(directory).replace("%", "%%")}
EnvironmentFile={str(env_file).replace("%", "%%")}
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart={" ".join(unit_argument(arg) for arg in args)}
TimeoutStartSec=180
UMask=0077
{hardening}"""
    timer = f"""[Unit]
Description=Check WIUT Social Registrar every ten seconds ({mode})

[Timer]
OnActiveSec=10s
OnUnitInactiveSec=10s
AccuracySec=1s
Unit={name}.service

[Install]
WantedBy=timers.target
"""
    return name, service, timer


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["production", "dev", "external"], required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--url", default="")
    parser.add_argument("--public-url", default="")
    args = parser.parse_args(argv)
    root, env_file = args.root.resolve(), args.env_file.resolve()
    name, service, timer = units(args.mode, root, env_file, args.url, args.public_url)
    if not env_file.is_file():
        parser.error("The selected private environment file does not exist")
    production = args.mode == "production"
    if production:
        if os.getuid() != 0:
            parser.error("Production monitoring must be installed as root")
        source = Path(__file__).resolve().parents[1] / "monitoring"
        target = root / "operations/monitoring"
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.resolve() != target.resolve():
            shutil.copytree(
                source, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__")
            )
        destination = Path("/etc/systemd/system")
        ctl = ["systemctl"]
    else:
        if not (root / ".venv/bin/python").is_file():
            parser.error("Create the project's .venv first")
        destination = Path.home() / ".config/systemd/user"
        ctl = ["systemctl", "--user"]
    destination.mkdir(parents=True, exist_ok=True)
    for suffix, content in (("service", service), ("timer", timer)):
        path = destination / (name + "." + suffix)
        path.write_text(content)
        path.chmod(0o644)
    subprocess.run(
        [
            "systemd-analyze",
            *([] if production else ["--user"]),
            "verify",
            str(destination / (name + ".service")),
            str(destination / (name + ".timer")),
        ],
        check=True,
    )
    subprocess.run([*ctl, "daemon-reload"], check=True)
    subprocess.run([*ctl, "enable", "--now", name + ".timer"], check=True)
    print("Independent monitor installed: " + name + ".timer")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
