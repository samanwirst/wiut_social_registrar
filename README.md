# WIUT Social Registrar

A Telegram bot for student and event registration. On first use, send your student ID, open Outlook, and enter the six-digit verification code from the email. Then share your own phone number using Telegram's contact button and select your current education level (CIFS, Level 4, Level 5, or Level 6) using inline buttons to complete registration and see your profile. The bot uses aiogram 3, Microsoft Graph v1.0, MSAL, and async SQLAlchemy.

Registration is open to everyone in private chats. Verification emails use a fixed template; Telegram users cannot send arbitrary emails. Registered users view only their own linked profile with `/me`; the bot does not offer student-directory searches. The Graph core retains its local console lookup and email tools.

Local mode uses SQLite. Production mode requires PostgreSQL. Both use the same models and Alembic migrations, applied automatically at startup.

Production releases from `main`, GitHub Actions deployment, IP-based HTTPS, private
backups, and a separate development bot are documented in [deployment.md](docs/deployment.md).
That guide also covers the optional `REGISTRAR_TELEGRAM_API_IPV4` setting for a
container-specific Telegram routing override when the server cannot reach its DNS-selected address.

## Before you start

You need:

- Docker Engine with Docker Compose v2+, or Docker Desktop. Python is installed inside the image.
- A Telegram bot token from [BotFather](https://t.me/BotFather).
- A work or school Microsoft account and a Microsoft Entra public-client application in its tenant. Your tenant must allow the required app registration and delegated user consent.
- Outbound HTTPS access to Telegram, Microsoft sign-in, and Microsoft Graph. The chat bot needs no inbound ports or domain. The optional organizer Mini App needs an address reachable from the Telegram device: local HTTPS works for development; public HTTPS supports other devices and production. SQLite runs locally; the production Compose configuration includes PostgreSQL.

Download and extract the project archive, or clone the repository:

```bash
git clone --branch main https://github.com/samanwirst/wiut_social_registrar.git
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

The check applies database migrations and verifies Telegram and Outlook, then exits without consuming Telegram updates. Open your bot in a private Telegram chat, send `/start`, then your student ID with any leading zeroes. Open Outlook and send the emailed six-digit code back to the bot. A matching code verifies your email and opens the **Share phone number** button. Tap it and confirm sharing your own Telegram contact. Then select **CIFS**, **Level 4**, **Level 5**, or **Level 6** using the inline buttons to complete registration and display your profile.

The bot uses the official [Telegram contact request button](https://core.telegram.org/bots/api#keyboardbutton). It accepts a contact only when its Telegram user ID matches the sender; forwarded contacts, other people's contacts, and numbers typed as text do not complete registration. The phone step survives restarts, and `/start` restores the button without emailing another code. Existing email-verified users are also asked to share their phone number once before viewing their profile. This temporary reply keyboard is removed after the contact is saved. It is the only reply keyboard: Telegram supports `request_contact` only on reply buttons; all menu, education, and event navigation buttons are inline.

The education step also survives restarts. `/start` restores its inline buttons; typing a level as text does not select it. Existing registered users without a saved education level are asked to choose it once, while their verified email, phone, original registration time, and event participation are preserved. Repeated clicks cannot overwrite a completed selection.

Codes expire after 10 minutes and allow five incorrect attempts. `/resend` issues a new code and invalidates the old one. Requests have a 60-second cooldown and a limit of five per hour for a Telegram user or mailbox. Restarting the bot preserves pending codes, limits, and completed registrations.

After registration, `/start` resumes any unfinished event questionnaire or sends a short welcome without a profile card or inline buttons. The welcome also removes reply keyboards left by older bot versions. `/me` shows only the completed profile linked to the Telegram sender, including their education level, from the local database without an Outlook request. It takes no arguments and works only in private chats. Sending an ID or other text after registration does not search for students; text is accepted as an answer when an event questionnaire is active. Event organizers open the panel with `/panel`. `/help` explains the workflow. `/info` presents the project with a cover image and the credit "Mukhammadiev Samandar, WestDevs", and links to the author, club and GitHub repository. It is available before registration too.

### Telegram profile and command menu

The bot presents registration as four steps: student ID, Outlook verification, own phone
contact, and education level. Messages use ordinary Telegram entities for headings and
copyable IDs; student names and event text stay literal.

The native **Menu** button adapts to the user. Before registration it offers `/start`,
`/resend`, `/help` and `/info`. Registered students see `/new_event`, `/me`, `/help` and
`/info`; `/panel` appears after `/new_event` only for event organizers when the panel is
configured. `/me` sits immediately before `/help`, and `/info` is last. Role changes update the menu
immediately. Updates are cached with bounded memory, and a failed menu update does not
block registration. Groups do not inherit the private-chat command list.

Profile copy lives in `app/bot_profile.py`; its avatar assets are in `app/assets/`.
Preview the public name, About text, description and initial commands without credentials:

```bash
python -m app.bot_profile
```

Apply them to your bot using its private configuration:

```bash
python -m app.bot_profile --apply --photo
# Docker:
docker compose run --rm bot python -m app.bot_profile --env-file /config/.env --apply --photo
```

This uses the official [Telegram profile methods](https://core.telegram.org/bots/api#setmyname),
[profile photo upload](https://core.telegram.org/bots/api#setmyprofilephoto), and
[command scopes](https://core.telegram.org/bots/api#botcommandscope). It does not start polling,
read student records, use Outlook, or send chat messages. Omit `--photo` on subsequent runs
to avoid another photo upload. Text fields are updated only when different. Normal startup
sets the default command menu; per-chat menus are refreshed when users interact with the bot.

The **description picture** above “What can this bot do?” is a separate image from
the profile avatar. The ready-to-upload cover is
[`app/assets/telegram-description.png`](app/assets/telegram-description.png), exactly
**640 × 360 pixels**. In the official [@BotFather](https://t.me/BotFather), open
`/mybots` → your bot → **Edit Bot** → **Edit Description Picture**, then send this
PNG as a photo. [Telegram documents this setup in BotFather](https://core.telegram.org/bots/features#botfather);
the Bot API does not expose a description-picture setter, so `--apply --photo`
updates the profile avatar only. The preview command also prints the cover path
and these setup instructions. Generation details are in
[`app/assets/README.md`](app/assets/README.md).

### Events and QR registration

Registered students create events using `/new_event Welcome Night` (name up to 200 characters). `/new_event` without a name creates an event named "New Event". Event creation is available only through this command; there is no New Event button or plain-text shortcut. The bot saves the event and returns a short text confirmation with **Manage event** when the Mini App is configured. The creation message contains no QR image, registration link, or registration button. Open the **QR** tab in the organizer panel to download the QR code or copy the registration link. Each event has a random UUID; the bot username is discovered through Telegram rather than configured in the source.

Scan the QR with an ordinary phone camera and open the HTTPS link. It takes the student into the bot using a [Telegram deep link](https://core.telegram.org/bots/features#deep-linking), such as `https://t.me/your_bot?start=event_<uuid>`. Telegram may ask the student to press **Start** before delivering the link to the bot.

- A fully registered student is enrolled immediately if the event has no questions. Otherwise the bot asks the event's questions in chat before enrolling them.
- A new student is asked for their student ID, Outlook code, own Telegram contact, and current education level. The event is saved while they register. Selecting their education level completes student registration and enrolls them into saved events without questions. Saved events with questions continue into a chat questionnaire.
- The latest event invitation survives restarts. Scanning another event replaces any unfinished event registration and discards its draft answers. Student ID verification, contact sharing, and completed event registrations are preserved.
- Repeated scans, concurrent requests, and another Telegram account linked to the same Outlook profile do not create duplicate participation. The organizer is enrolled only if they also open the event link.

Creating events is available to all registered users in private chats. Event links enroll the person who opens them.

### Organizer Mini App and event questionnaires

Create an event with `/new_event Event name`, then open **Manage event** below the confirmation or use `/panel`. Event creation remains a bot command. The Mini App configures existing events and displays their participant tables.

The Mini App becomes available only after a student **successfully creates their first event with `/new_event`**. Ordinary students do not see Mini App buttons or its help entry; `/panel` asks them to create an event first. Attending someone else's event does not unlock the panel. This permission is checked on every API request as well, so an old or shared Mini App link cannot bypass it. Organizer status is derived from saved event ownership and survives bot restarts.

The organizer workspace provides:

- Event name and description, and an open/closed registration switch.
- A dedicated **QR** tab with a copyable registration link and a downloadable **PNG with a transparent background**. QR images load only when this tab is opened; the other pages focus on editing and participants.
- Up to **20 questions**, with **Text response (TR)** and **Multiple choice (MC)** answer types. Questions can be reordered, made optional, or removed before the first questionnaire is submitted. Choice answers use individual fields with **Add option** and remove controls, like Telegram polls. Each question accepts 2–20 unique options of up to 100 characters; Enter moves to the next option or adds a new one.
- A participant table with **10 rows per page**, contact details, Level, and one column per question. **Refresh** fetches current answers. Answers expire automatically according to the event's retention period.
- Automatic expiration of extra answers after **30 days by default**. Retention is managed by the server.

Set up questions **before sharing the QR code**. Events start open and have no questions, preserving immediate enrollment until questions are added. Students already enrolled are not asked to register again; their extra answer cells show a dash.

Students fill questionnaires **inside the bot chat**, not in the Mini App. The bot sends one question at a time. Text and number questions accept a message; choice questions save the selected inline option and immediately advance, without checkmarks or a **Continue** step. Optional questions have **Skip**. `/start` restores progress. Opening another event QR immediately leaves the unfinished event and starts the selected event; earlier draft answers are discarded and its old inline buttons cannot answer the new questionnaire. Reopening the same event preserves progress. An invalid or closed event link leaves the current questionnaire intact.

Choice answers retain their existing storage format. Previously saved selections and questionnaire tokens survive upgrades; options and **Continue** buttons from the old multi-select UI remain valid for the current question. Choosing an option preserves earlier selections for that question and advances immediately. No migration or form-revision change is needed.

Unfinished answers are stored separately in `event_form_sessions` for **one hour of inactivity**, so restarts do not lose progress. They are removed after expiration or successful submission. Final answers live only in `event_answers`, with their own expiration timestamp; neither profile tables nor analytics events receive their contents. The final answer, questionnaire removal, and event enrollment commit in one database transaction. Repeated QR scans or old inline buttons cannot create duplicate participation or overwrite answers. Questions become immutable after the first submitted questionnaire, even after its answers expire, to preserve their meaning. Event details and registration status remain editable in the Mini App.

Expired answers disappear from API results immediately. A cleanup job physically deletes expired answers and drafts at bot startup and every **10 minutes**, including when the Mini App is disabled. Database backups have their own lifecycle; align backup retention with your chosen answer retention policy if you make backups.

### Enable the Mini App

The bot and the Mini App API run in the **same Python process** and share the same SQLite/PostgreSQL database and Alembic migrations. The interface uses React, TypeScript, and [TelegramUI](https://github.com/telegram-mini-apps-dev/TelegramUI), with the official [Telegram Web App SDK](https://core.telegram.org/bots/webapps#initializing-mini-apps) for client integration. TelegramUI is a community UI kit, rather than a Telegram-owned SDK. Its `AppRoot`, lists, cells, tabs, form controls, buttons, and notifications follow Telegram's interface and current theme. Questionnaires remain in the bot chat.

Docker builds the frontend automatically using `npm ci` and the committed lockfile, then copies the static output into the Python image. **Node.js is only needed for building, not running the bot.** For a Python installation, install Node.js 22.12+ (Node.js 24 LTS recommended) and build once from the project root:

```bash
npm ci --prefix frontend
npm run build --prefix frontend
```

Repeat the build after editing `frontend/src/`. The generated `frontend/dist/` is ignored by Git and served by `aiohttp` on the same origin as `/api`. No frontend environment variables or credentials are required; the bot token and Outlook credentials stay in the server's `.env`. Telegram authorization is still validated on the server, and access requires completed registration and at least one created event.

See [Mini App interface references](docs/miniapp-design.md) for the public product examples, layout decisions, and theme regression checks used by the organizer panel.

Normal Telegram bots require an **HTTPS** URL, which can be local for development if the Telegram client can reach it and trusts its certificate. A public HTTPS endpoint is the usual deployment option for other users; a public domain is not required for every local test. Telegram's separate test environment also permits HTTP. Leave `MINI_APP_URL` empty to disable the web server and its launch buttons while retaining the bot and chat questionnaires. There is no authentication bypass for local browsers.

### Local HTTPS with the existing bot

The approach in [synphora's local development script](https://github.com/samanwirst/synphora/blob/main/client/synphora_app/package.json) is to serve HTTPS with a local certificate. Its aiogram bot uses the regular Telegram API. This project supports the same setup directly in `aiohttp`, without Next.js or another web server.

Install [mkcert using its platform instructions](https://github.com/FiloSottile/mkcert#installation). The commands below install a development CA into your machine's trust stores and issue a certificate for loopback addresses. Run these steps yourself when you want to enable local HTTPS; the bot does not change system certificate trust.

```bash
mkdir -p .local/certificates
mkcert -install
mkcert -cert-file .local/certificates/localhost.pem \
  -key-file .local/certificates/localhost-key.pem localhost 127.0.0.1 ::1
chmod 600 .local/certificates/localhost-key.pem
```

For Python running with the project's root `.env`, add:

```dotenv
TELEGRAM_TEST_ENVIRONMENT=false
MINI_APP_URL=https://127.0.0.1:8443
MINI_APP_HOST=127.0.0.1
MINI_APP_PORT=8443
MINI_APP_TLS_CERT_FILE=.local/certificates/localhost.pem
MINI_APP_TLS_KEY_FILE=.local/certificates/localhost-key.pem
```

Certificate paths are relative to the selected `.env` file, not the current working directory. Set both paths to enable direct TLS; leave both empty when TLS is handled by a reverse proxy. Direct TLS requires a matching, unencrypted private key and an HTTPS URL. The bot never prompts for a key password.

Start normally with `python main.py`, open `https://127.0.0.1:8443/health` to verify HTTPS, and use Telegram Desktop **on the same computer**: register, create an event with `/new_event`, and open `/panel`. The certificate must be trusted by Telegram's embedded webview too; if the client reports a certificate error, fix that client's trust or use Telegram's official HTTP test environment below. Opening the URL in a plain browser alone does not supply signed Telegram authentication.

For Docker, put the settings in `.local/.env` with paths `certificates/localhost.pem` and `certificates/localhost-key.pem`, since `.local/` is mounted at `/config/`. Run the local override, which publishes only a loopback port and does not start Caddy:

```bash
docker compose --env-file .local/.env \
  -f compose.yaml -f compose.miniapp.local.yaml up -d --build
```

Keep `MINI_APP_PORT=8443` for the host port. The override sets the container's listening port to 8080 and forwards 8443 to it. Private certificate files stay outside the image under `.local/`. A phone's `127.0.0.1` points to the phone, so it cannot reach a server on your PC that way. For another device, use a reachable LAN address with the right certificate/client trust, or public HTTPS.

### Official Telegram test environment over HTTP

[Telegram documents a separate test environment](https://core.telegram.org/bots/webapps#using-bots-in-the-test-environment) that accepts HTTP Mini App URLs. In Telegram Desktop, open **Settings**, then **Shift + Alt + right-click Add Account** and select **Test Server**. Create a test account and a new bot through that environment's BotFather. Its token is separate from your existing bot token.

Use a separate private `.env` file with the usual Graph configuration and these settings:

```dotenv
APP_ENV=local
TELEGRAM_BOT_TOKEN=your_test_environment_bot_token
TELEGRAM_TEST_ENVIRONMENT=true
MINI_APP_URL=http://127.0.0.1:8080
MINI_APP_HOST=127.0.0.1
MINI_APP_PORT=8080
MINI_APP_TLS_CERT_FILE=
MINI_APP_TLS_KEY_FILE=
```

Start with `python main.py --env-file /path/to/test/.env`. The flag selects aiogram's built-in `TEST` API server and its `/test/` routes. It does not run a local Bot API server and does not turn a production bot token into a test token. The default SQLite database is `registrations.telegram-test.sqlite3` beside the selected `.env`, keeping test Telegram identities separate from normal identities. If you explicitly set `DATABASE_URL`, choose a separate test database yourself. `APP_ENV=production` rejects this flag; ordinary bots continue to reject HTTP Mini App URLs.

This mode keeps Telegram signature validation, completed student registration, and the `/new_event` organizer requirement. For Docker, use `compose.miniapp.local.yaml` as above with the test settings. Your normal Telegram app/account environment cannot communicate with a test bot; switch the client to the test environment first. Test environment registration uses the existing Outlook verification workflow.

### Public HTTPS deployment

Once you have a domain, point its DNS to your server, allow incoming ports 80/443, and set these values in the bot's `.env` (`.local/.env` for Docker):

```dotenv
MINI_APP_URL=https://events.example.com
MINI_APP_HOST=127.0.0.1
MINI_APP_PORT=8080
```

Use an HTTPS origin without a path, query string, or credentials. Local Python binds to loopback by default. The optional Mini App Compose override sets the container bind address to `0.0.0.0` and publishes HTTP **only on the host's loopback interface**. The base bot stack publishes no ports. An optional Caddy configuration is included to obtain and renew TLS certificates automatically:

```bash
docker compose --env-file .local/.env \
  -f compose.yaml -f compose.production.yaml -f compose.miniapp.yaml \
  up -d --build
```

For SQLite instead of PostgreSQL, omit `-f compose.production.yaml`. If ports 80/443 already belong to another reverse proxy, copy only the `bot` environment and loopback port mapping from `compose.miniapp.yaml` into your own override and forward HTTPS to that port. `deploy/Caddyfile` forwards requests to `bot:8080`; certificate data persists in Docker volumes. The frontend and `/api` must use the same origin. The local health endpoint is `http://127.0.0.1:8080/health` while the Mini App server is enabled.

Restart the bot, create your first event with `/new_event Event name`, and open **Manage event** below the confirmation or use `/panel` to receive a Web App button. Existing event creators already qualify. A separate Telegram Main Mini App or menu-button configuration in BotFather is optional; the included private-chat inline Web App buttons are sufficient.

Every API request sends raw `Telegram.WebApp.initData` in the `Authorization` header. The server validates its Telegram HMAC using aiogram, rejects duplicate fields, expired/future authentication data, and bot identities, and checks completed student registration and event ownership. Authentication expires after one hour; reopen the panel to refresh it. Telegram IDs from query parameters or unverified browser data are never used for access. Responses disable caching, values render as literal text, and request bodies/authentication headers are not logged. Each event has a revision to prevent one editor window from silently overwriting another.

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
| `telegram_users` | Telegram ID, first and last name, current username, language, Premium flag, first/last seen and profile update timestamps, Outlook profile link, email verification time (`verified_at`), shared phone number (`phone_number`), contact sharing time (`phone_shared_at`), selected current education level (`education_level`), selection time (`education_selected_at`), and completed registration time (`registered_at`). |
| `outlook_profiles` | Student ID, Microsoft Graph ID, UPN, display/given/family names, email addresses, first seen and last refresh timestamps. |
| `verification_challenges` | Pending profile association, HMAC code hash and nonce, expiry, remaining attempts, and email submission status. Consumed codes are deleted. |
| `registration_events` | Timestamped registration requests, email outcomes, verification successes/failures, contact sharing, education selection, registration completion, cancellations, bot starts, and lookup outcomes. Event details contain reasons, counters, and the selected education level where useful. |
| `events` | Event UUID, name, description, creator's Telegram ID, creation time, registration status, question definitions, answer retention days, editor revision, and whether submitted questions are locked. |
| `event_registrations` | Event UUID, participant's Telegram ID and Outlook profile link, and enrollment time. Unique constraints allow one participation per event and student profile or Telegram account. |
| `pending_event_registrations` | Telegram user, event UUID, and first invitation time while account registration or event questions are incomplete. Rows are removed after enrollment or cancellation. |
| `event_form_sessions` | One unfinished chat questionnaire per Telegram user: event, form revision, current question, button nonce, partial answers, and one-hour inactivity expiration. |
| `event_answers` | Event enrollment link, submitted additional answers, submission time, and expiration time. Default retention is 30 days. |

Telegram profiles are refreshed from incoming updates. Outlook profiles are refreshed from Graph; successful email verification links the two identities, and education selection after contact sharing completes registration. Education levels are self-reported through the inline buttons. The phone number is normalized with a leading `+`; contact names and vCards are not duplicated in the database. Phone numbers are never included in analytics event details. These tables support registration funnels, active-user counts, education/language/Premium breakdowns, cohort analysis, and delivery/failure metrics. Timestamps are stored in UTC and relevant identity/time fields are indexed.

The Outlook fields above are available through the existing basic-profile permissions. Missing source fields stay null. Bot-only capability flags, entire Telegram updates, general chat history, access tokens, and plaintext verification codes are not stored in the database. Explicit questionnaire answers are the temporary exception described above. Codes are hashed with a separate secret in `.env`, and SQLite files have permissions `600`.

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

The image runs as an unprivileged user. `.dockerignore` excludes credentials, local runtime data, Git metadata, and virtual environments. The runtime image contains only application code and production dependencies. The base bot stack uses long polling and publishes no ports. The optional Mini App override maps HTTP to host loopback and exposes public HTTPS through Caddy.

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
| Mini App port is already in use | Stop the existing bot or web server before launching another instance. If using a user service, manage it with `systemctl --user restart wiut-social-registrar` and stop it before running `python main.py` manually. Changing the port also requires updating `MINI_APP_URL`. |
| Mini App frontend is not built | Run `npm ci --prefix frontend` followed by `npm run build --prefix frontend`, or rebuild the Docker image. |
| Microsoft Graph returns HTTP 403 | Check the signed-in account, delegated consent, and tenant policies. |
| Student not found | Check the full ID, including leading zeroes, and `GRAPH_STUDENT_DOMAIN`. |
| Code expired or attempts exhausted | Use `/resend` after the cooldown; enter the new code from Outlook. |
| Email submission status unknown | Check Outlook first. A received code still works; sending is never repeated automatically. |
| Database startup error | Check `APP_ENV`, database credentials, connectivity, and migrations. Production requires PostgreSQL. |

## Run without Docker

Requires Python 3.11+. Python 3.12 is used in the Docker image.
For the Mini App, also install Node.js 22.12+ and build the interface as shown under [Enable the Mini App](#enable-the-mini-app).

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

The structure follows `referral_tgbot`: `BotApp`, separate handler routers, and injected services.
See [architecture and responsibility boundaries](docs/architecture.md) and
[contributor setup](CONTRIBUTING.md). Coding-agent guidance is in [AGENTS.md](AGENTS.md).

```text
main.py                              # Telegram entry point
config.py                            # Bot configuration
app/bot.py                           # Bot, dispatcher, middleware, shutdown
app/middleware.py                    # Private-chat access and shared per-user context
app/handlers/                        # Registration, verification, own profile, and event commands
app/dialogs/                         # Reusable registration and questionnaire chat steps
app/services/registrar_service.py    # Graph lookups and fixed verification mail template
app/services/registration_service.py # Registration workflow
app/services/event_service.py        # Local PNG QR generation with Segno
app/models.py                        # Shared SQLAlchemy models for SQLite and PostgreSQL
app/repositories.py                  # Stable student registration lifecycle API
app/registration/                    # Challenge persistence, hashing, profiles, analytics records
app/event_repository.py              # Stable facade for focused event persistence components
app/events/                          # Settings, enrollment, organizer queries, answer retention
app/event_forms.py                   # Question and answer validation
app/surveys.py                       # Persistent chat questionnaire progress
app/miniapp/                         # HTTP auth, routes, assets, application and TLS lifecycle
app/services/answer_cleanup.py       # Answer expiration, independent of the HTTP server
frontend/src/                        # React/TypeScript organizer panel using TelegramUI
frontend/src/hooks/                  # Shared request, navigation, draft and Telegram integration
frontend/package-lock.json           # Reproducible frontend dependency versions
frontend/dist/                       # Generated static assets served by aiohttp (ignored)
app/db.py                            # Async database lifecycle and migrations
migrations/                          # Versioned Alembic schema migrations
cli.py                               # Local console tools and sign-in
registrar/                           # Graph client, MSAL authentication, models
registrar/transport.py               # Graph HTTP errors and bounded retry policy
registrar/environment.py             # Shared private dotenv reading and credential persistence
Dockerfile                           # Runtime image and test target
compose.yaml                         # Bot service and persistent configuration mount
compose.production.yaml              # PostgreSQL production override
compose.miniapp.yaml                 # Optional public HTTPS reverse proxy
compose.miniapp.local.yaml           # Loopback-only Mini App development, HTTP or direct TLS
deploy/Caddyfile                     # Automatic TLS and Mini App proxy configuration
tests/                               # Tests with mocked Telegram and HTTP transports
Makefile                             # Lint, build, test, browser and Docker checks
pyproject.toml                       # Ruff configuration
scripts/test_postgres.py              # Disposable PostgreSQL integration-test runner
```

Synchronous Graph and MSAL operations share one background worker, keeping Telegram's event loop responsive and serializing HTTP session access and cache writes. Database operations are asynchronous with a separate transaction per operation. The bot processes at most 16 updates concurrently and isolates updates per user. PostgreSQL row/advisory locks and SQLite write transactions protect verification and mailbox rate limits from concurrent requests.

## Tests

For the complete development checks, run `make check` from an activated virtual environment
after installing `requirements-dev.txt` and frontend packages. It runs Ruff, builds the
frontend, and runs pytest. `make postgres-test` adds an isolated PostgreSQL container;
`make browser` runs browser QA. See [testing.md](docs/testing.md) for setup and isolation details.

Run tests in Docker without credentials:

```bash
docker build --target test -t wiut-social-registrar:test .
```

Or use a local virtual environment:

```bash
python -m pip install -r requirements-dev.txt
npm ci --prefix frontend
npm run build --prefix frontend
python -m pytest -q
```

Tests cover registration, own-contact checks, phone-step persistence, event QR links, duplicate enrollment, pending invitations, atomic student/event registration, participant API authorization and pagination, retired chat-menu handling, chat questionnaires and inline MCQ choices, partial answer expiry, retention changes, answer deletion, stale buttons, concurrent submissions, signed Mini App authentication, ownership checks on every API endpoint, schema migrations, profile persistence, code expiry, wrong attempts, replay prevention, resends, rate limits, Telegram routing, and the Graph/console core. Telegram and Graph transports are mocked; tests send no real messages or emails.

Optional browser integration checks use a temporary database, synthetic students, the real API, and a simulated Telegram host. After building the frontend, run:

```bash
python -m pip install playwright
python -m playwright install chromium
python tests/browser_miniapp.py
```

The script also detects a system Chromium installation. Set `CHROMIUM_EXECUTABLE` to choose a browser explicitly. It checks saved questions, locked forms, participant pagination, themes, mobile layouts, and unsaved changes; screenshots contain only synthetic data and are saved to a temporary directory.

Set `TEST_DATABASE_URL` to an async PostgreSQL URL for a dedicated database whose name ends in `_test` to run repository and API tests against PostgreSQL as well. These tests truncate application tables in that database between cases. SQLite tests run without an external service.

The project is licensed under [GNU GPL v3](LICENSE).
