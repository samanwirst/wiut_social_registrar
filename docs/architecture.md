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
| Selected QR designs and atomic PNG replacement | `app/events/qr_designs.py` |
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
| Dependency probes and private runtime heartbeat | `app/services/runtime_health.py` |
| Independent process supervision and administrator delivery | `monitoring/`, `deploy/install_watchdog.py` |
| Image generation jobs, provider access, and bounded temporary designs | `app/services/qr_designer.py` |
| QR artwork composition and scan verification | `app/services/qr_art.py` |
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

The bot exposes a completed student profile only through `/me` and the registration
completion confirmation. The profile middleware resolves it from `event.from_user.id`;
command arguments and message text never select a different student. `/me` reads
saved data without a Graph request and does not consume questionnaire answers. Plain
IDs are accepted for initial verification only. Directory lookup remains a console
capability, separate from the Telegram transport. Organizers retain ownership-checked
access to their own event participants through the existing panel.

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

Selecting a different valid event discards the user's other pending invitations and
questionnaire draft in the same transaction that selects or enrolls in the new event.
The user lock serializes competing selections. Failed event validation leaves the
current progress intact; completed registrations and student verification are preserved.
Reopening the same event keeps its draft and question token. Old buttons from a
discarded questionnaire cannot submit answers to the newly selected event.

Shared UTC clocks are injectable. Drafts expire after one hour of inactivity; final answers
default to 30 days. Expired answers are filtered on reads and physically deleted at startup
and every ten minutes. The cleanup service runs without an HTTP server. It does not delete
profiles, attendance, or analytics, and answer contents never enter those permanent tables.

`BotApp` owns all runtime resources. Shutdown uses `AsyncExitStack` to close every resource
even when another close fails. HTTP startup cleans up its runner on bind/setup failures or
cancellation. Cleanup task cancellation and HTTP close are repeatable.
After polling stops, the update-drain middleware waits for active chat handlers, including
updates queued on a student's isolation lock, before database and network clients close.
Already committed registration stages and questionnaire tokens remain in the database.

## Graph and console

`registrar/` remains a synchronous, independently usable package. `GraphClient` owns
profile lookup, bounded caching, sender identity, and mail operations. `GraphTransport`
owns HTTP response handling, authentication refresh, bounded read retries, and safe errors.
Ambiguous mail submission is never automatically retried. MSAL owns authentication.

`RegistrarService` serializes Graph and MSAL calls through a single background worker.
Normal startup defers Outlook availability to `RuntimeHealth`; strict diagnostic mode still
requires it. A timed-out Outlook probe stays attached and does not enqueue another read.
No email submission is retried by monitoring. Administrator IDs grant notification delivery
only. See [monitoring.md](monitoring.md) for probe thresholds and operational limitations.
`RegistrationService` only composes fixed verification email delivery with challenge
reservation/status updates. Arbitrary email remains an explicitly confirmed console feature.
The CLI separates argument parsing, a single lookup/email command, and interactive lookup.

`registrar/environment.py` is the only dotenv reader/writer. It preserves explicit environment
precedence, disables interpolation, and saves renewable credentials with private permissions.
Graph configuration, database validation, and Mini App URL/TLS validation have separate owners.

## Frontend

Components render the existing TelegramUI interface. Focused hooks own shared behavior:

- `useRemoteResource`: per-consumer request state, retry, abort, and stale-response suppression.
- `useObjectUrl`: object URL allocation and cleanup for QR downloads.
- `useQrDesign`: restoring the server's selected design and active job, bounded submissions,
  abortable polling, elapsed/cooldown timers, and optional device-local background preference.
- `useWorkspace`: initial loading and guarded navigation between event lists and details.
- `useEventDraft`: immutable edits, revision-aware saves, and duplicate-save protection.
- `useUnsavedChanges`: browser unload and Telegram closing/navigation guards.
- `useTelegramBack` and `useTelegramTheme`: Telegram/browser event subscriptions and cleanup.

API transport stays in `api.ts`. It sends signed `initData`, times out both headers and body,
and never caches personal responses. The backend checks organizer status and event ownership.
Browser state is not an authorization source. QR generation stays lazy on its own tab, and
students complete questionnaires in the bot chat.

QR designs use a separate asynchronous Cloudflare client owned by the HTTP application's
cleanup context. No Graph worker or database transaction is held during generation.
Submissions, job reads, and both image exports independently verify signed identity and
event ownership. Temporary IDs never authorize access. A bounded in-memory job cache
stores only ownership, status, and checked PNG exports; prompts live only in the active
generation task. Provider responses and credentials are excluded from logs and API errors.
`event_qr_designs` stores one selected design per event, with both PNGs committed together
after scan verification. Metadata reads omit image blobs. Selection, status, image reads,
and reset independently enforce organizer ownership. Reopening a fresh WebView or clearing
the job cache restores selection from the database without another provider request.
A failed generation/save leaves the previous row intact; ready status is published only
after persistence commits. Reset awaits cancellation of pending generation before deleting
selection, preventing late completion from restoring a deliberately removed design.
Reset preserves cooldown history. Student and questionnaire transactions are unaffected.
QR composition and scan checks run in background threads. Connected paths and rounded
finder eyes retain the matrix's sampling centers outside the illustration. The center
uses part of H-level error correction; a bounded local layout search requires the same
illustration placement to scan in both backgrounds before either PNG is published.
The illustration's white paper is removed only where connected to its outer boundary.
Shutdown cancels pending provider tasks, awaits them, closes the client, and clears the
temporary cache; the selected design remains in the database.
Job metadata includes elapsed seconds and remaining cooldown; quota waits return HTTP 429
with both a JSON `retry_after` and a `Retry-After` header. Repeated requests for an already
active event job return that job. Client polling failures, generation failures, and cooldown
notices are separate states, so reconnecting never creates an image or hides a valid result.

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


## General forms, table editing, and messages

`events` is the stable storage/API facade for all forms, with an optional `department` label.
There is no form-type selection or type-dependent behavior. The public `/api/forms` routes
and `/new_form` command use the same ownership, enrollment, questionnaire, and QR implementations
as legacy event links; `/new_event` remains a creation alias. The unused `kind` storage column
is retained for compatibility with the applied 0007 migration and is not exposed by the API.
No parallel profile or participation system is introduced.

`app/events/table.py` owns typed organizer columns and edits to temporary question responses.
`app/table_fields.py` validates them. Edits lock the owned form and registration, compare row
and column revisions, and commit one cell with its revision increment. Columns have a separate
revision from form/questionnaire settings. Student identities/contacts are never write targets.
`EventRegistration.table_expires_at` is a durable non-extending deadline, backfilled on upgrade;
shortened deadlines survive cleanup and later retention extensions. New organizer values are
in `event_table_values`, filtered/cleaned like answers. Removing a column redacts its values.

`app/broadcasts.py` owns audience snapshots, hourly limits, preview revisions, confirmation,
cancellation, claims, outcomes, and recipient retention. It locks the owner before an owned
broadcast when both locks are needed; queue operations lock a broadcast before a recipient.
PostgreSQL claims use SKIP LOCKED. SQLite retains BEGIN IMMEDIATE. No network call holds a lock.
`app/dialogs/broadcasts.py` and `app/handlers/broadcast_handler.py` compose native Telegram
ForceReply previews. `app/dialogs/broadcast_content.py` preserves native entities, rich blocks,
and media while appending an italic attribution from the owner-checked form title. This is
frozen into the preview before confirmation; delivery still copies the saved Telegram message.
They consume only replies to the active owner's saved prompt;
regular commands, verification, and questionnaire answers retain their handlers and state.
Completed history is filtered before pagination and appears below the People table. Its
`message_<uuid>` bot links check the requesting owner and completed state before copying
the immutable sent preview back to that owner. `original_message_id` links new copies to
the organizer's original through ReplyParameters; old records keep working without it.
This uses supported bot links because private bot chats have no direct message permalinks.
Both message references expire with the existing thirty-day recipient cleanup.

`app/services/broadcast_worker.py` is the sole runtime dispatcher. It claims one recipient,
commits the claim, copies the bot-owned preview, then commits the outcome. Retries are restricted
to definite Telegram flood rejections with a five-attempt budget. Ambiguous copies and abandoned
claims are recorded as unknown instead of replayed. Cancellation stops pending work, including
rejected in-flight work being requeued. Thirty days later recipient rows/source references are
removed; aggregate counts remain. Worker startup/shutdown and safe health reporting belong to
BotApp. The worker operates even without the HTTP server.

The Mini App uses labeled TelegramUI checkboxes, typed inline cell editors, optimistic revisions,
explicit saves, and the native Telegram link handoff. It stores neither selections nor table data
in localStorage. Official design and transport references are in
[forms-and-messages.md](forms-and-messages.md).

`useCellEditor` owns the shared revision-aware cell mutation and duplicate-save guard. Inline
editors and `AnswerDetails` retain separate drafts while using that same transport behavior.
`useTextOverflow` observes the three-line preview. One full-answer surface is owned by the
mounted People view, preserving its audience, pagination, and table position. The workspace's
existing BackButton handler checks the active detail callback before leaving the form; no
second native back listener is registered. Nested dirty state joins the form's existing closing
confirmation/unload protection. `useVisualViewport` subscribes only while the full editor is open
and releases listeners on unmount. Full answers remain plain text and never enter browser storage.
