# Backend rules

- `BotApp` composes services and owns their lifecycle. aiogram workflow data carries
  fixed dependencies; middleware checks transport access and loads per-user context.
- Do not import one handler from another. Shared chat behavior belongs in `dialogs/`.
- `registration_state.py` owns completion rules used by lookup, enrollment, and panel access.
- `events/` components own event settings, enrollment, organizer queries, and retention.
  `event_repository.py` is their stable facade; do not add SQL to it.
- `miniapp/` handles HTTP authentication, serialization, assets, and server lifecycle.
  Do not access database sessions from HTTP routes.
- Use `Database.transaction(write=True)` for writes. Preserve SQLite `BEGIN IMMEDIATE`,
  PostgreSQL row/advisory locks, and user-before-event lock ordering.
- Cross-table enrollment helpers accept an existing session. They must not open or commit
  another transaction, or call Graph while database locks are held.
- Inject UTC clocks for time-dependent persistence. Keep questionnaire drafts and final
  answers separate from permanent profiles and analytics.
- Answer cleanup must run even when the HTTP server is disabled. Close all started
  resources on failure and cancellation; teardown must tolerate repeated calls.
