# WIUT Social Registrar

A Telegram bot for student registration and profile lookup. On first use, send your student ID, open Outlook, and enter the six-digit verification code from the email. Then share your own phone number using Telegram's contact button to complete registration and see your profile. The bot uses aiogram 3, Microsoft Graph v1.0, MSAL, and async SQLAlchemy.

Registration is open to everyone in private chats. Verification emails use a fixed template; Telegram users cannot send arbitrary emails. Registered users can look up profiles by sending an ID as text. The Graph core also provides local console email tools.

Local mode uses SQLite. Production mode requires PostgreSQL. Both use the same models and Alembic migrations, applied automatically at startup.

## Before you start

You need:

- Docker Engine with Docker Compose v2+, or Docker Desktop. Python is installed inside the image.
- A Telegram bot token from [BotFather](https://t.me/BotFather).
- A work or school Microsoft account and a Microsoft Entra public-client application in its tenant. Your tenant must allow the required app registration and delegated user consent.
- Outbound HTTPS access to Telegram, Microsoft sign-in, and Microsoft Graph. No inbound ports or domain are required. SQLite runs locally; the production Compose configuration includes PostgreSQL.

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
5. During the first console sign-in, grant the delegated scopes requested by the core: `User.Read`, `User.ReadBasic.All`, and `Mail.Send`. The bot uses `Mail.Send` for registration codes.

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

The check applies database migrations and verifies Telegram and Outlook, then exits without consuming Telegram updates. Open your bot in a private Telegram chat, send `/start`, then your student ID with any leading zeroes. Open Outlook and send the emailed six-digit code back to the bot. A matching code verifies your email and opens the **Share phone number** button. Tap it and confirm sharing your own Telegram contact to complete registration and display your profile.

The bot uses the official [Telegram contact request button](https://core.telegram.org/bots/api#keyboardbutton). It accepts a contact only when its Telegram user ID matches the sender; forwarded contacts, other people's contacts, and numbers typed as text do not complete registration. The phone step survives restarts, and `/start` restores the button without emailing another code. Existing email-verified users are also asked to share their phone number once before using profile lookup.

Codes expire after 10 minutes and allow five incorrect attempts. `/resend` issues a new code and invalidates the old one; `/cancel` clears the pending registration so you can enter another ID. Requests have a 60-second cooldown and a limit of five per hour for a Telegram user or mailbox. Restarting the bot preserves pending codes, limits, and completed registrations.

After registration, `/start` shows your own profile without sending another email. Plain student IDs still perform lookups. `/help` explains the workflow.

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

SQLite data is stored in `.local/registrations.sqlite3` for Docker, or next to the selected `.env` for local Python. Stop the bot before copying a SQLite database for backup.

Use one process per configuration file and one polling instance per Telegram token. Stop the bot before running console commands against the same `.env`, then start it again. Configuration changes are read when a process starts.

## Production with PostgreSQL

Use the same private `.local/.env`, with `DATABASE_URL` empty, and set `POSTGRES_PASSWORD`. The template provides `POSTGRES_HOST=postgres`, `POSTGRES_PORT=5432`, `POSTGRES_USER=registrar`, and `POSTGRES_DB=registrar`. Use a dedicated password; keep the file private.

Build and complete the Outlook login above, then run:

```bash
docker compose --env-file .local/.env -f compose.yaml -f compose.production.yaml up -d --build
docker compose --env-file .local/.env -f compose.yaml -f compose.production.yaml logs --tail=50 -f bot
```

The override selects `APP_ENV=production`, starts PostgreSQL 17, waits for its health check, and starts the bot. Database credentials are loaded from `.env`; the application constructs the connection URL with proper password escaping. PostgreSQL data persists in the `postgres_data` named volume, with no public database port.

For an existing PostgreSQL server, set `APP_ENV=production` and `DATABASE_URL=postgresql+asyncpg://...` in `.local/.env` and use the base Compose file alone. Production refuses SQLite and never silently falls back to a local database. Switching backends selects a separate database; it does not copy local registration data into PostgreSQL.

Use the same two Compose files for production status, logs, stop, and down commands. `docker compose down` preserves the database volume; deleting that volume deletes production data.

Create a PostgreSQL backup while the database is running:

```bash
docker compose --env-file .local/.env -f compose.yaml -f compose.production.yaml exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > .local/registrations.dump
```

Back up `.local/.env` along with the database. `BOT_VERIFICATION_SECRET` is generated automatically on first startup and stored there. Keep it stable so pending codes remain verifiable after a restart or restore.

## Stored registration data and analytics

| Table | Stored data |
| --- | --- |
| `telegram_users` | Telegram ID, first and last name, current username, language, Premium flag, first/last seen and profile update timestamps, Outlook profile link, email verification time (`verified_at`), shared phone number (`phone_number`), contact sharing time (`phone_shared_at`), and completed registration time (`registered_at`). |
| `outlook_profiles` | Student ID, Microsoft Graph ID, UPN, display/given/family names, email addresses, first seen and last refresh timestamps. |
| `verification_challenges` | Pending profile association, HMAC code hash and nonce, expiry, remaining attempts, and email submission status. Consumed codes are deleted. |
| `registration_events` | Timestamped registration requests, email outcomes, verification successes/failures, registration completion after contact sharing, cancellations, bot starts, and lookup outcomes. Event details contain reasons and counters where useful. |

Telegram profiles are refreshed from incoming updates. Outlook profiles are refreshed from Graph; successful email verification links the two identities, and sharing the user's own contact completes registration. The phone number is normalized with a leading `+`; contact names and vCards are not duplicated in the database. Phone numbers are never included in analytics event details. These tables support registration funnels, active-user counts, language/Premium breakdowns, cohort analysis, and delivery/failure metrics. Timestamps are stored in UTC and relevant identity/time fields are indexed.

The Outlook fields above are available through the existing basic-profile permissions. Missing source fields stay null. Bot-only capability flags, entire Telegram updates, chat contents, access tokens, and plaintext verification codes are not stored in the database. Codes are hashed with a separate secret in `.env`, and SQLite files have permissions `600`.

For example, registration totals by language use ordinary SQL on both backends:

```sql
SELECT language_code, COUNT(*) AS users,
       COUNT(verified_at) AS email_verified_users,
       COUNT(registered_at) AS registered_users
FROM telegram_users
GROUP BY language_code;
```

## Database migrations

The bot applies pending Alembic migrations before polling, including when run with `--check`. To apply them separately:

```bash
python -m app.migrate --env-file .env
# In Docker:
docker compose run --rm bot python -m app.migrate --env-file /config/.env
```

To add a migration during development, change the models, then generate and review it:

```bash
alembic -x env_file=.env revision --autogenerate -m 'Describe the schema change'
```

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
| Code expired or attempts exhausted | Use `/resend` after the cooldown; enter the new code from Outlook. |
| Email submission status unknown | Check Outlook first. A received code still works; sending is never repeated automatically. |
| Database startup error | Check `APP_ENV`, database credentials, connectivity, and migrations. Production requires PostgreSQL. |

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

The last command previews an email. Add `--send` to submit it explicitly, or use `--body-file letter.txt` for UTF-8 text. These arbitrary email tools are available only through the local console. The bot sends fixed registration emails. Inside Docker, use the same commands with `docker compose run --rm bot python cli.py --env-file /config/.env` and stop the bot first.

Microsoft Graph sends email from the signed-in account through `/me/sendMail` and saves it in Sent Items. HTTP 202 confirms acceptance for sending, not delivery. Ambiguous submission failures are never retried automatically; check Sent Items before resubmitting.

Lookup JSON contains `student_id`, `name`, `email`, `account`, `email_addresses`, `source`, `graph_id`, `given_name`, and `surname`. A missing student is `null`. Results go to stdout; diagnostics go to stderr. Console exit codes are `0` for success, `1` for no matching student, `2` for an error, and `130` for Ctrl+C.

`GraphClient.find_student()` returns a `Student` or `None` and raises `GraphError` on failure. Students are fetched by exact UPN, using the signed-in account's domain by default. Successful lookups are cached for 5 minutes, up to 256 entries. HTTP 403 and network errors are never reported as missing students.

## Configuration reference

| Variable | Default | Purpose |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | Required for the bot | Token from BotFather. |
| `APP_ENV` | `local` | `local` selects SQLite by default; `production` requires PostgreSQL. |
| `DATABASE_URL` | Automatic | Optional explicit SQLAlchemy async database URL. |
| `BOT_VERIFICATION_SECRET` | Generated automatically | Secret HMAC key for verification codes; persisted in `.env`. |
| `POSTGRES_HOST` / `POSTGRES_PORT` | `postgres` / `5432` | Production database address when no explicit URL is set. |
| `POSTGRES_USER` / `POSTGRES_DB` | `registrar` | Production database user and name. |
| `POSTGRES_PASSWORD` | Required for bundled production DB | Database password stored in `.env`. |
| `GRAPH_CLIENT_ID` | Required | Your Entra application ID. |
| `GRAPH_TENANT_ID` | `organizations` | Your tenant UUID, or organizational accounts. |
| `GRAPH_ACCOUNT` | Empty | Optional sign-in UPN restriction. |
| `GRAPH_STUDENT_DOMAIN` | Signed-in UPN domain | Student UPN domain override. |
| `GRAPH_TIMEOUT_SECONDS` | `15` | HTTP read and authentication timeout. |
| `GRAPH_CACHE_TTL_SECONDS` | `300` | Student profile cache lifetime. |
| `GRAPH_DEBUG` | `false` | Graph request diagnostics. |
| `GRAPH_TOKEN_CACHE_B64` | Empty | Secret MSAL cache, saved automatically after sign-in. |

`APP_UID` and `APP_GID` are optional host environment variables used by Compose, not application credentials. Store database credentials, the verification secret, and the MSAL cache in the private `.env` file. Microsoft passwords and client secrets are not stored.

## Architecture

The structure follows `referral_tgbot`: `BotApp`, separate handler routers, and a service injected through middleware.

```text
main.py                              # Telegram entry point
config.py                            # Bot configuration
app/bot.py                           # Bot, dispatcher, middleware, shutdown
app/handlers/                        # Registration, verification, and plain ID lookup
app/services/registrar_service.py    # Graph lookups and fixed verification mail template
app/services/registration_service.py # Registration workflow
app/models.py                        # Shared SQLAlchemy models for SQLite and PostgreSQL
app/repositories.py                  # Profiles, verification transactions, analytics events
app/db.py                            # Async database lifecycle and migrations
migrations/                          # Versioned Alembic schema migrations
cli.py                               # Local console tools and sign-in
registrar/                           # Graph client, MSAL authentication, models
Dockerfile                           # Runtime image and test target
compose.yaml                         # Bot service and persistent configuration mount
compose.production.yaml              # PostgreSQL production override
tests/                               # Tests with mocked Telegram and HTTP transports
```

Synchronous Graph and MSAL operations share one background worker, keeping Telegram's event loop responsive and serializing HTTP session access and cache writes. Database operations are asynchronous with a separate transaction per operation. The bot processes at most 16 updates concurrently and isolates updates per user. PostgreSQL row/advisory locks and SQLite write transactions protect verification and mailbox rate limits from concurrent requests.

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

Tests cover registration, own-contact checks, phone-step persistence, migration of existing email-verified users, profile persistence, code expiry, wrong attempts, replay prevention, resends, concurrent requests, rate limits, Telegram routing, and the Graph/console core. Telegram and Graph transports are mocked; tests send no real messages or emails.

Set `TEST_DATABASE_URL` to an async PostgreSQL URL for a dedicated database whose name ends in `_test` to run repository tests against PostgreSQL as well. These tests truncate the four application tables in that database between cases. SQLite tests run without an external service.

The project is licensed under [GNU GPL v3](LICENSE).
