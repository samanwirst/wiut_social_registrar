# Microsoft Graph core rules

- This package stays synchronous and independent of aiogram, SQLAlchemy, and the bot.
- Preserve exact student UPN matching, leading zeroes, account restrictions, and bounded caches.
- Keep HTTP retries and safe errors in the transport; profile and mail behavior belongs
  to `GraphClient`. A read failure must not become a missing-student result.
- Retry reads only within existing limits. Never automatically retry an ambiguous email
  submission; HTTP 202 means accepted, not delivered.
- MSAL owns authentication. Persist its renewable cache through `environment.py` with
  private file permissions. Do not implement password login or add Graph permissions.
- Preserve the console's JSON stdout, stderr diagnostics, explicit `--send`, and exit codes.
