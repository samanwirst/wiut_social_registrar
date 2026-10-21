# Architecture and ownership

The application has three entry points: `main.py` composes and runs the Telegram bot,
`cli.py` provides synchronous console commands, and `frontend/src/main.tsx` renders the
organizer Mini App. The HTTP server shares the bot's process and database. Refactoring
preserves their public commands, API payloads, configuration, and database schema.

## Backend boundaries

| Responsibility | Owner |
| --- | --- |
| Runtime composition and shutdown | `app/bot.py` (`BotApp`) |
| Telegram transport checks and dynamic context | `app/middleware.py` |
| Commands, filters, callback parsing | `app/handlers/` |
| Shared registration prompts and questionnaire responses | `app/dialogs/` |
| Email/phone/education completion rules | `app/registration_state.py` |
| Registration lifecycle and stable public API | `app/repositories.py` |
| Challenge reservation, rate limits, and consumption | `app/registration/verification.py` |
| Code hashing and verification limits | `app/registration/policy.py` |
| Outlook profile synchronization and analytics record creation | `app/registration/profiles.py`, `history.py` |
| Stable event API, without SQL | `app/event_repository.py` |
| Event metadata, ownership, and revisions | `app/events/settings.py`, `access.py` |
| Event editor input validation | `app/events/validation.py` |
| Invitations and atomic enrollment | `app/events/enrollment.py` |
| Authorized event/member pages and contact projection | `app/events/queries.py` |
| Answer retention changes and deletion | `app/events/retention.py` |
| Shared pagination bounds | `app/pagination.py` |
| Question definitions, answer validation, and answer transitions | `app/event_forms.py` |
| Persistent questionnaire progress | `app/surveys.py` |
| HTTP application wiring | `app/miniapp/application.py` |
| Signed Telegram authentication | `app/miniapp/auth.py` |
| HTTP input/output, headers, and static allowlist | `app/miniapp/routes.py`, `middleware.py`, `assets.py` |
| HTTP/TLS startup and shutdown | `app/miniapp/server.py` |
| Independent answer expiration worker | `app/services/answer_cleanup.py` |
| Database sessions, dialect inserts, and migrations | `app/db.py` |
| Telegram, database, and Mini App configuration | `config.py`, `app/configuration/` |

The repository facades retain their existing public methods so callers need not learn
storage internals. Their components own the implementations; there is no dynamic method
forwarding, inheritance hierarchy, shared session, or duplicated implementation behind them.
Transport code cannot open a repository transaction. SQL projections stay in query components.

`Dispatcher` workflow data contains fixed service dependencies. A shared middleware pipeline
validates private chats and loads user context for messages and callbacks. Handlers do not
import other handlers. Reusable dialogs own shared Telegram interaction steps, including
the narrow handling of an unchanged inline keyboard.

## Transactions and concurrency

Each operation creates its own `AsyncSession` using `Database.transaction()`. Write
transactions use SQLite `BEGIN IMMEDIATE`; PostgreSQL uses row locks and a mailbox advisory
lock for verification requests. No Graph request runs while a database write lock is held.

Preserve these transaction boundaries:

1. Verification reservation, rate-limit history, and challenge replacement commit together.
   A wrong attempt commits its decremented counter before returning a user-facing error.
2. Completing education selection, marking the profile registered, recording analytics,
   and enrolling pending events without questions commit together.
3. The last questionnaire answer, final temporary answers, attendance, removal of the draft,
   and removal of the invitation commit together. A partial failure rolls everything back.

Where both rows are needed, lock the Telegram user before the event. Transaction helpers
such as `enroll_pending_events()` and `submit_answers_in_transaction()` join the caller's
session; they never start or commit another transaction. Unique constraints make repeated
scans and concurrent requests idempotent for both Telegram identity and Outlook profile.

Shared UTC clocks are injectable. Drafts expire after one hour of inactivity; final answers
default to 30 days. Expired answers are filtered on reads and physically deleted at startup
and every ten minutes. The cleanup service runs without an HTTP server. It does not delete
profiles, attendance, or analytics, and answer contents never enter those permanent tables.

`BotApp` owns all runtime resources. Shutdown uses `AsyncExitStack` to close every resource
even when another close fails. HTTP startup cleans up its runner on bind/setup failures or
cancellation. Cleanup task cancellation and HTTP close are repeatable.

## Graph and console

`registrar/` remains a synchronous, independently usable package. `GraphClient` owns
profile lookup, bounded caching, sender identity, and mail operations. `GraphTransport`
owns HTTP response handling, authentication refresh, bounded read retries, and safe errors.
Ambiguous mail submission is never automatically retried. MSAL owns authentication.

`RegistrarService` serializes Graph and MSAL calls through a single background worker.
`RegistrationService` only composes fixed verification email delivery with challenge
reservation/status updates. Arbitrary email remains an explicitly confirmed console feature.
The CLI separates argument parsing, a single lookup/email command, and interactive lookup.

`registrar/environment.py` is the only dotenv reader/writer. It preserves explicit environment
precedence, disables interpolation, and saves renewable credentials with private permissions.
Graph configuration, database validation, and Mini App URL/TLS validation have separate owners.

## Frontend

Components render the existing TelegramUI interface. Focused hooks own shared behavior:

- `useRemoteResource`: per-consumer request state, retry, abort, and stale-response suppression.
- `useObjectUrl`: object URL allocation and cleanup for transparent QR downloads.
- `useWorkspace`: initial loading and guarded navigation between event lists and details.
- `useEventDraft`: immutable edits, revision-aware saves, and duplicate-save protection.
- `useUnsavedChanges`: browser unload and Telegram closing/navigation guards.
- `useTelegramBack` and `useTelegramTheme`: Telegram/browser event subscriptions and cleanup.

API transport stays in `api.ts`. It sends signed `initData`, times out both headers and body,
and never caches personal responses. The backend checks organizer status and event ownership.
Browser state is not an authorization source. QR generation stays lazy on its own tab, and
students complete questionnaires in the bot chat.

## Design basis

These boundaries are project design decisions, informed by the following official guidance:

- [aiogram dependency injection](https://docs.aiogram.dev/en/latest/dispatcher/dependency_injection.html)
  for workflow data and middleware context.
- [SQLAlchemy async sessions](https://docs.sqlalchemy.org/en/21/orm/extensions/asyncio.html#using-asyncsession-with-concurrent-tasks)
  for one session per task and explicit transaction ownership.
- [aiohttp application lifecycle](https://docs.aiohttp.org/en/stable/web_advanced.html#graceful-shutdown)
  and [Python AsyncExitStack](https://docs.python.org/3/library/contextlib.html#contextlib.AsyncExitStack)
  for resource ownership and cleanup.
- [React custom hooks](https://react.dev/learn/reusing-logic-with-custom-hooks)
  and [effect cleanup](https://react.dev/learn/synchronizing-with-effects)
  for shared behavior with independent state and cleaned-up subscriptions.
- [OpenAI project instructions](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
  for concise root instructions, scoped `AGENTS.md` files, and linked support documents.
- [PEP 8](https://peps.python.org/pep-0008/) and
  [Ruff configuration](https://docs.astral.sh/ruff/configuration/) for consistent, automated Python style.

No framework prescribes this exact directory layout. Avoid adding layers unless a repeated
rule or an independently changing responsibility justifies one.
