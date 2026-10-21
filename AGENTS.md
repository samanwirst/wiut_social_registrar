# Repository guide

WIUT Social Registrar is an aiogram bot, a React Telegram Mini App, and a synchronous
Microsoft Graph core. Keep source, documentation, and user-visible strings in English.

## Start here

- Read [CONTRIBUTING.md](CONTRIBUTING.md) for setup and supported commands.
- Read [docs/architecture.md](docs/architecture.md) before moving responsibilities.
- Read [docs/testing.md](docs/testing.md) for isolated database and browser checks.
- Follow scoped instructions in `app/`, `registrar/`, `frontend/`, and `tests/`.

## Implementation

- Handlers and HTTP routes translate transport input/output. Put shared conversation
  steps in `app/dialogs/`, business rules in their domain modules, and SQL in persistence.
- Extract repeated knowledge into its owning module. Prefer plain functions and composition
  to generic repository frameworks, dynamic forwarding, or one-use abstractions.
- Keep `RegistrationRepository`, `EventRepository`, and `GraphClient` public interfaces
  stable when practical. Their internal components can change without duplicating rules.
- Keep database migrations append-only. Refactoring alone must not change the schema.
- All configuration comes from the selected private `.env` and explicit environment
  overrides. Update `.env.example` and README when adding configuration.
- Preserve signed Telegram authentication, organizer ownership checks, idempotent enrollment,
  rate limits, and the atomic transactions documented in the architecture guide.

## Verification

From an activated virtual environment with development dependencies installed:

```bash
make check
make browser  # after changes affecting Mini App behavior; requires Playwright
make docker-test  # after packaging or dependency changes
```

Use the PostgreSQL instructions in `docs/testing.md` after changing SQL, locks, or
transaction boundaries. Report exactly which checks ran and any remaining limitations.

## Local and external state

- Never print or commit `.env`, token caches, verification codes, private keys, real
  registrations, answer contents, or `.local/outlook_users.json`.
- Tests use synthetic data, mocked Graph/Telegram transports, and temporary databases.
  Never point tests at a user's database or send real email/Telegram messages.
- Do not start a second polling process for an existing bot token. A local user service
  may already own the Mini App port; tests use ephemeral ports and their own application.
- Follow the user's current instructions for commits, pushes, and deployment.

## Code Review Rules

- Flag paths that authorize from query parameters, unsigned Telegram data, or an event
  UUID without checking its owner. Use the authenticated request identity.
- Flag split commits for profile completion and pending enrollment, or for final form
  answers and attendance. Keep each operation inside one transaction.
- Flag shared `AsyncSession` instances, Graph access outside its single worker, unbounded
  retries, and automatic retries of an ambiguously accepted email.
