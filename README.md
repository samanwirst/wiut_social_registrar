# WIUT Social Registrar

A public Telegram bot that looks up a student by ID and returns their name, email address, and account. Send an ID as text or use `/find STUDENT_ID`. The bot uses aiogram 3 and Microsoft Graph v1.0 with MSAL authentication.

Telegram users can only look up profiles. The Graph core also provides local console tools for email previews and explicit email submission.

## Before you start

You need:

- Docker Engine with Docker Compose v2+, or Docker Desktop. Python is installed inside the image.
- A Telegram bot token from [BotFather](https://t.me/BotFather).
- A work or school Microsoft account and a Microsoft Entra public-client application in its tenant. Your tenant must allow the required app registration and delegated user consent.
- Outbound HTTPS access to Telegram, Microsoft sign-in, and Microsoft Graph. No inbound ports, domain, or database are required.

Download and extract the project archive, or clone the repository:

```bash
git clone --branch dev https://github.com/samanwirst/wiut_social_registrar.git
cd wiut_social_registrar
```

Run the commands below from the project directory. Shell examples use Linux/macOS or WSL on Windows.

## Configure Microsoft sign-in

For a new deployment, create your own application:

1. Open the [Microsoft Entra admin center](https://entra.microsoft.com/) and go to **App registrations > New registration**.
2. Enter an application name and select **Accounts in this organizational directory only**.
3. Copy the **Application (client) ID** and **Directory (tenant) ID** from the application overview.
4. Open **Authentication** and enable **Allow public client flows**, then save. Device-code authentication does not require a redirect URI or client secret.
5. During the first console sign-in, grant the delegated scopes requested by the core: `User.Read`, `User.ReadBasic.All`, and `Mail.Send`. The Telegram interface exposes profile lookup only.

The account used here could grant these permissions through user consent. Other tenants can have different policies. If registration or consent is blocked, the application cannot complete sign-in until the required access is available.

Microsoft's instructions: [configure a public-client application](https://learn.microsoft.com/en-us/entra/identity-platform/scenario-desktop-app-configuration).

## Docker quick start

### 1. Create your private configuration

```bash
mkdir -p .local
test -f .local/.env || cp .env.example .local/.env
chmod 700 .local
chmod 600 .local/.env
```

Edit **`.local/.env`** and fill in:

```dotenv
TELEGRAM_BOT_TOKEN=your-bot-token
GRAPH_CLIENT_ID=your-application-client-id
GRAPH_TENANT_ID=your-directory-tenant-id
```

These are placeholders; replace them with your own values. Leave `GRAPH_TOKEN_CACHE_B64` empty on the first run. Optionally set `GRAPH_ACCOUNT` to your sign-in UPN, such as `00000000@university.edu`.

If you already have a working project-root `.env`, you can copy it to `.local/.env` instead of starting from the template. Docker reads `.local/.env`; local Python commands read the project-root `.env` by default. Both locations are excluded from Git and Docker builds.

### 2. Set the container's file ownership and build

On Linux/macOS, set these variables in the terminal where you run Compose:

```bash
export APP_UID="$(id -u)"
export APP_GID="$(id -g)"
docker compose build bot
```

Repeat the two exports in a new terminal. Compose defaults to UID/GID `1000:1000` if they are unset. Matching your host user allows the container to update the private configuration without changing its ownership.

### 3. Sign in to Outlook

Run this once for a new configuration, or when Microsoft requires reauthentication:

```bash
docker compose run --rm bot python cli.py --env-file /config/.env --login
```

MSAL prints an official Microsoft verification URL and a one-time code. Open the URL in your normal browser, enter the code, select your account, and complete sign-in and consent. No browser is needed inside the container.

The renewable MSAL cache is saved automatically to `.local/.env`. The bot refreshes tokens silently and never sends sign-in codes to Telegram users.

### 4. Check and start the bot

```bash
docker compose run --rm bot python main.py --env-file /config/.env --check
docker compose up -d bot
docker compose logs --tail=50 -f bot
```

The check verifies Telegram and Outlook, then exits without consuming Telegram updates. Open your bot in Telegram, send `/start`, then a student ID such as `00000001`. `/find 00000001` and `/help` are also supported. Leading zeroes are preserved.

### Everyday commands

```bash
docker compose ps                       # Container status
docker compose logs --tail=100 bot      # Recent logs
docker compose stop bot                # Stop before reauthentication or console use
docker compose up -d bot                # Start again
docker compose up -d --build bot        # Rebuild after updating the source
docker compose down                    # Remove the container and project network
```

`.local/.env` stays on the host across container restarts, rebuilds, and `docker compose down`. Back up this file privately if moving the deployment. Base64 encoding does not encrypt the token cache.

Use one process per configuration file and one polling instance per Telegram token. Stop the bot before running console commands against the same `.env`, then start it again. Configuration changes are read when a process starts.

## Why configuration is mounted as a directory

Compose mounts `.local/` at `/config/` with write access. The rest of the container filesystem is read-only. MSAL cache persistence replaces `.env` atomically, so mounting just the file would prevent reliable updates. The source `.env` is read by Python directly, rather than injected as container environment variables, so a stale environment value cannot override a refreshed token cache.

The image runs as an unprivileged user. `.dockerignore` excludes credentials, local runtime data, Git metadata, and virtual environments. The runtime image contains only application code and production dependencies. The bot uses long polling and publishes no ports.

Docker references: [bind mounts](https://docs.docker.com/engine/storage/bind-mounts/), [Compose services](https://docs.docker.com/reference/compose-file/services/).

## Troubleshooting

| Symptom | What to do |
| --- | --- |
| Missing bind source directory | Create `.local/` and `.local/.env` before using Compose. |
| Permission denied while saving the cache | Export `APP_UID` and `APP_GID` as shown above; ensure your user owns `.local/` and its `.env`. |
| Invalid Telegram token | Correct `TELEGRAM_BOT_TOKEN` in `.local/.env`, then restart the bot. |
| Outlook sign-in required or token cache corrupted | Stop the bot, run the console login command again, then start it. |
| A Telegram webhook is configured | Disable the existing webhook before using long polling. The bot leaves existing webhook settings intact. |
| Telegram polling conflict | Stop the other instance using the same bot token. |
| Microsoft Graph returns HTTP 403 | Check the signed-in account, delegated consent, and tenant policies. |
| Student not found | Check the full ID, including leading zeroes, and `GRAPH_STUDENT_DOMAIN`. |

## Run without Docker

Requires Python 3.11+. Python 3.12 is used in the Docker image.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
test -f .env || cp .env.example .env
chmod 600 .env
```

Fill in the project-root `.env`, then run:

```bash
python cli.py --login
python main.py --check
python main.py
```

Use `--env-file PATH` to select another configuration file. `python main.py --debug` enables Graph request methods, paths, HTTP status codes, timings, and cache hits. Tokens, authorization headers, and full error responses are excluded from logs.

## Console tools and Graph core

```bash
python cli.py                             # Interactive student lookup
python cli.py --id 00000001 --json         # One profile as JSON
python cli.py --login                      # Sign in again
python cli.py --logout                     # Remove the local token cache
python cli.py --id 00000001 --subject 'Subject' --body 'Body'
```

The last command previews an email. Add `--send` to submit it explicitly, or use `--body-file letter.txt` for UTF-8 text. These email tools are available only through the local console, not Telegram. Inside Docker, use the same commands with `docker compose run --rm bot python cli.py --env-file /config/.env` and stop the bot first.

Microsoft Graph sends email from the signed-in account through `/me/sendMail` and saves it in Sent Items. HTTP 202 confirms acceptance for sending, not delivery. Ambiguous submission failures are never retried automatically; check Sent Items before resubmitting.

Lookup JSON contains `student_id`, `name`, `email`, `account`, `email_addresses`, and `source`. A missing student is `null`. Results go to stdout; diagnostics go to stderr. Console exit codes are `0` for success, `1` for no matching student, `2` for an error, and `130` for Ctrl+C.

`GraphClient.find_student()` returns a `Student` or `None` and raises `GraphError` on failure. Students are fetched by exact UPN, using the signed-in account's domain by default. Successful lookups are cached for 5 minutes, up to 256 entries. HTTP 403 and network errors are never reported as missing students.

## Configuration reference

| Variable | Default | Purpose |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | Required for the bot | Token from BotFather. |
| `GRAPH_CLIENT_ID` | Required | Your Entra application ID. |
| `GRAPH_TENANT_ID` | `organizations` | Your tenant UUID, or organizational accounts. |
| `GRAPH_ACCOUNT` | Empty | Optional sign-in UPN restriction. |
| `GRAPH_STUDENT_DOMAIN` | Signed-in UPN domain | Student UPN domain override. |
| `GRAPH_TIMEOUT_SECONDS` | `15` | HTTP read and authentication timeout. |
| `GRAPH_CACHE_TTL_SECONDS` | `300` | Student profile cache lifetime. |
| `GRAPH_DEBUG` | `false` | Graph request diagnostics. |
| `GRAPH_TOKEN_CACHE_B64` | Empty | Secret MSAL cache, saved automatically after sign-in. |

`APP_UID` and `APP_GID` are optional host environment variables used by Compose, not application credentials. Store deployment credentials and the MSAL cache in the private `.env` file. Passwords and client secrets are not stored.

## Architecture

The structure follows `referral_tgbot`: `BotApp`, separate handler routers, and a service injected through middleware.

```text
main.py                              # Telegram entry point
config.py                            # Bot configuration
app/bot.py                           # Bot, dispatcher, middleware, shutdown
app/handlers/                        # /start, /help, /find, and plain ID input
app/services/registrar_service.py    # Read-only async adapter to Graph
cli.py                               # Local console tools and sign-in
registrar/                           # Graph client, MSAL authentication, models
Dockerfile                           # Runtime image and test target
compose.yaml                         # Bot service and persistent configuration mount
tests/                               # Tests with mocked Telegram and HTTP transports
```

Synchronous Graph and MSAL operations share one background worker, keeping Telegram's event loop responsive and serializing HTTP session access and cache writes. The bot processes at most 16 updates concurrently and requires no database.

## Tests

Run tests in Docker without credentials:

```bash
docker build --target test -t wiut-social-registrar:test .
```

Or use a local virtual environment:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Tests cover Telegram routing, public lookup, missing students, validation, errors, background execution, token refresh, private cache persistence, and console email behavior. Telegram and Graph transports are mocked; tests send no real messages or emails.

The project is licensed under [GNU GPL v3](LICENSE).
