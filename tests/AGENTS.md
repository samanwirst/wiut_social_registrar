# Test rules

- Test observable behavior and transaction invariants, not class names or forwarding wrappers.
- Use `repository` from `conftest.py` for database behavior. It runs on temporary SQLite
  and optionally a dedicated PostgreSQL database ending in `_test`.
- Graph, Telegram, SMTP, and real student data are excluded. Use `example.test` addresses,
  synthetic Telegram users, and dummy credentials.
- Legacy migration tests may build historical schemas and call public persistence helpers.
  Never edit an applied migration just to make current tests pass.
- Browser QA starts its own aiohttp application, signs synthetic Telegram data, and uses
  a temporary database. Preserve the real API/data path, authorization, and theme checks.
- When separating lifecycle code, verify failure cleanup and cancellation as well as success.
