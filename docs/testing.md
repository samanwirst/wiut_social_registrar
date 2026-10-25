# Verification

See [CONTRIBUTING.md](../CONTRIBUTING.md) for installing Python development dependencies
and frontend packages. Real `.env` files, Telegram accounts, and Microsoft access are not needed.

## Normal checks

```bash
make check
```

This runs Ruff lint/format checks, TypeScript checking and Vite build, then pytest.
Use `make test` for a focused rerun after backend changes; Mini App static-asset tests
still require the frontend to have been built once. `make format` applies Ruff fixes.
Historical migration files are excluded from formatting and remain append-only.

Tests exercise the public behavior of registration, OTP limits/replay, own-contact and
education steps, concurrent/idempotent event enrollment, transaction rollback, temporary
questionnaires/answers, Mini App authorization, API serialization, pagination, and Graph/CLI
behavior. Lifecycle regressions cover retention retry/cancellation and cleanup after failures.
Monitoring regressions inject Outlook expiry/timeouts, failed email submissions, polling
failures/recovery, stale heartbeats, supervisor probe failures, and ambiguous restart attempts.
All Bot API, Docker, and systemd transports in those tests are mocked; operational setup alerts
are an explicit manual action outside pytest. Tests verify private atomic state, recipient
allowlists, notification deduplication/backoff, bounded repair, and status-aware `/start` resume.

## PostgreSQL

```bash
make postgres-test
```

The helper starts an isolated PostgreSQL 17 container, binds an ephemeral loopback port,
generates a password in memory, and supplies its own database URL to pytest. The database
ends in `_test`; its files live on tmpfs. The container and data are removed in `finally`,
including after a failed test run. It never reads or changes the application's `.env` or DB.
Docker must be available; allow time for the image pull on the first run.

For an already provisioned **dedicated disposable test database**, set `TEST_DATABASE_URL`
to its async PostgreSQL URL and run `make test`. Tests truncate application tables between
cases, and reject database names that do not end in `_test`. Do not use real registration data.

The shared `repository` fixture runs once on SQLite and once on PostgreSQL when that URL
is present. SQLite-only historical migration tests remain isolated in temporary files.

## Browser flow

```bash
python -m pip install playwright
python -m playwright install chromium
make browser
```

A system Chromium installation can be used instead; set `CHROMIUM_EXECUTABLE` explicitly
when needed. Browser checks start a separate aiohttp application on an ephemeral port,
use signed synthetic Telegram initialization data, and exercise the real API and temporary DB.
The SDK host is simulated; Graph and Telegram never receive messages.

Checks cover event editing and save recovery, locked questions, poll option controls,
ten-row pagination, contact fields, lazy PNG QR exports with both backgrounds, asynchronous
AI design submission/resumption with a synthetic provider and real QR scan checks, native BackButton,
generation stages, elapsed/cooldown displays, reconnecting without duplicate generation,
preservation of the previous image after a failed regeneration, restoration in a completely
fresh browser context, background preference after reload, and reconnecting a selection read
without briefly displaying the standard QR,
unsaved changes, Android/iOS layouts, light/dark themes, contrast, and safe areas. Screenshots
contain synthetic data and are saved under a printed temporary directory for visual inspection.

QR design regressions also check visible illustration colors, enclosed white details,
rounded finder eyes, transparent four-module margins, multiple invitation lengths,
rotated scans, and shared-layout repair when either background fails verification.
Persistence checks cover application restart/cache expiry, identical PNG bytes, owner-only
selection/reset, atomic concurrent replacement, failed saves, and reset during generation
without losing rate-limit history. These repository fixtures run on PostgreSQL as well.

## Container checks

```bash
make docker-test
docker build --target runtime -t wiut-social-registrar:local .
```

The test stage installs pinned development tools, runs lint/format checks and pytest, and
builds the frontend through the Node stage. The runtime stage excludes development tools
and test code. Private configuration, local DB files, caches, node_modules, and host build
output are excluded from the Docker context.

Compose configuration can be validated without starting services:

```bash
docker compose config --quiet
docker compose --env-file .env.example -f compose.yaml -f compose.miniapp.local.yaml config --quiet
```

Production/public HTTPS overrides additionally require placeholder or real deployment
values for `POSTGRES_PASSWORD` and `MINI_APP_URL`. Do not print rendered configuration
that contains real values. `config --quiet` validates without displaying those values.


## Forms, table editing, and native broadcasts

`tests/test_forms_tables_broadcasts.py` runs on isolated SQLite/PostgreSQL. It covers forms and
departments, owner-only cell/column mutations, conflict rejection, immutable verified profiles,
expiry after cleanup/retention extension, migration of existing profiles/answers, audience and
confirmation idempotency, flood-wait budgets, interruption recovery, cancellation, and recipient
retention. `test_forms_api.py` covers signed identity, other owners, tampering, and transport.
`test_broadcast_chat.py` feeds real aiogram updates with synthetic text, rich content, photos,
and documents and mocks all Bot API calls. It checks italic form attribution, UTF-16 entities,
text/caption limits, nested rich media, and exact saved copies through confirmation and delivery,
including when the form is renamed after preparing the preview.
Browser QA selects people on two pages, creates an audience, checks the native compose URL,
edits number/choice cells, adds columns, changes the department, and opens a Finished link
under People while drafts remain hidden. Repository/API checks cover filtered pagination,
active-queue refresh metadata, owner-only sent-message links, exact sent copies, and original
message reply references.
Its Telegram SDK stub intercepts the handoff; no real Telegram page or message is used.
