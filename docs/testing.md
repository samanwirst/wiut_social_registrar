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
ten-row pagination, contact fields, lazy transparent PNG QR export/download, native BackButton,
unsaved changes, Android/iOS layouts, light/dark themes, contrast, and safe areas. Screenshots
contain synthetic data and are saved under a printed temporary directory for visual inspection.

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
