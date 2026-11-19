# Product analytics

Open `MINI_APP_URL/admin` in a normal browser. This separate administrator website shares
the bot's existing HTTPS server and database. It does not need another domain, vendor
account or external analytics SDK. Master-Battery's local admin page informed the report
organization.

## Access and two-factor authentication

Keep administrator IDs in the selected private `.env` as `BOT_ADMIN_IDS=[976835256]`.
Set a password interactively, without putting it in shell arguments/history:

```bash
python -m app.analytics.setup --env-file .local/dev/.env
```

The command saves a salted scrypt hash as `ANALYTICS_ADMIN_PASSWORD_HASH`. Use a password
of 12–128 characters. Restart the existing bot service after changing configuration.
For Docker, run this module inside the existing container with `--env-file /config/.env`.
The password is currently shared by administrators; Telegram identity and codes are
individual. An empty hash disables the website while telemetry continues. Use HTTPS;
Secure session cookies cannot work over HTTP. Start the bot in Telegram before signing in.

Enter your numeric Telegram ID and password. The bot sends a six-digit code only to that
configured administrator's private chat. Codes expire in five minutes, permit five attempts,
are browser-bound and work once. A failed or ambiguously accepted send invalidates the code;
the website does not tell you to check Telegram after a failed send. Requests have persistent
per-administrator/global limits, a one-minute delivery cooldown and bounded hashing concurrency.

Opaque session tokens are hashed at rest. Cookies are Secure, HttpOnly, SameSite=Strict.
Sessions expire after eight hours or 30 minutes idle. Writes require the configured Origin
and CSRF protection. Logout revokes the session. Changing the password or removing an admin
invalidates sessions and pending challenges after the new configuration loads. Credentials
and codes never go in URLs or browser storage. The website cannot be embedded in frames.

`BOT_ADMIN_IDS` explicitly grants bot-wide analytics, including form names/question labels.
It does not grant participant downloads, answer contents, or organizer API access. Signed
organizer `initData` cannot authenticate to the admin API, and admin cookies cannot authorize
the organizer API. Ownership checks on existing organizer operations remain unchanged.

## Reports

- **Overview:** current inventory, period activity/new users/completions/submissions, daily
  activity, popular features, Microsoft submission outcomes and broadcast delivery statuses.
- **Registration:** first-seen cohort funnel, steps where inactive accounts paused,
  education/language distributions and day 1/7/30 return visits.
- **Forms:** opens, starts, submissions and per-question reached/answered/rejected counts,
  conversion, response time, switches to other forms and current active drafts.
- **Experience:** actions, platforms, visible screen engagement, normalized API performance,
  slow requests and fixed problem categories.
- **Users:** pseudonymous journeys and registration milestones. No student/contact data.
  Admin API row keys are internal Telegram IDs; displayed labels use HMAC pseudonyms.
- **Activity:** paginated event trail with outcome/source filters and allowlisted context.

Dates/buckets use UTC. Inventory and active-draft figures describe current state. Funnels
use users first seen in the selected period and milestones reached before its end, counting
each user once per stage. Return visits use fully elapsed 24-hour windows after first sight.
“Not answered” includes still-active attempts, not just abandonment. Response time includes
time away from chat and is capped at 24 hours. Visible engagement is sampled at most every
15 seconds. Browser events are observations, not authoritative business successes.

The collection-start timestamp is explicit: historical clicks/timings cannot be recreated.
Existing registration milestones and attendance are available immediately. Reports exceeding
the usage retention window have partial UX coverage. Missing telemetry is not proof of no use.

## Collection coverage

| Surface | Observations |
| --- | --- |
| Bot entry/commands | Private update/command/callback categories, duration, unhandled error category |
| Student registration | Step prompts/rejections, lookup timing, requested/accepted/unknown/failed email state, code failures, phone/education completion, cancellation |
| Forms in chat | Opens, attempt starts/resumes, questions reached/answered/rejected/skipped, time, form switches, atomic final enrollment |
| Organizer panel | Opens/platform/viewport, screen visits/engagement, button/switch/selection/field interactions, pagination, settings/questions/columns, answer editor, messaging, XLSX/QR delivery, QR design/background/link actions |
| Transport/jobs | Normalized API method/route/status/timing, browser network/runtime failures, Bot API method/result, QR generation, file delivery, durable broadcast enqueue/delivery |

Event names and categorical property values are allowlisted. Ingestion needs signed Telegram
authentication; form references require organizer ownership. Batches contain at most 20 events,
limited to 120/minute/user/process, with UUID deduplication. It collects no IP addresses,
full user agents, text-field/search values, answers, message content, passwords, codes,
prompts, file references or arbitrary exception strings. No replay/DOM recording or analytics
browser storage is used.

Anonymous participant milestones omit Telegram IDs. A random questionnaire-attempt ID supports
aggregate analysis without linking the attempt to the student or their other forms. These
milestones are absent from individual journeys. Bot-level action categories can still show
that someone interacted with the bot, without linking a particular anonymous form.

## Storage and reliability

Migration `0011_product_analytics` adds usage/authentication tables and nullable attempt metadata
to questionnaire drafts without resetting progress. Attendance/final answers and business
milestones commit together. Registration history remains separate, preserving email quotas.
`ANALYTICS_RETENTION_DAYS` defaults to 90, accepts 30–365 and affects usage events only.

Observational telemetry uses a bounded 2,000-event queue, 100-event inserts, five-second DB
timeouts and a bounded shutdown drain. It cannot make a registration wait for telemetry I/O.
Queue overflow, failed batches, abrupt termination or an offline/closed WebView can lose
observational events. The website shows drop/write-failure counters since process startup.
Durable business milestones remain in their owning transactions. The collector runs even
without the Mini App. Hourly cleanup deletes at most 5,000 expired usage rows per pass,
expired admin challenges/sessions and login attempts older than seven days. It does not delete
students, registration history, attendance or form answers.

Authentication follows [OWASP MFA](https://cheatsheetseries.owasp.org/cheatsheets/Multifactor_Authentication_Cheat_Sheet.html)
and [session management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)
guidance. No third-party collector receives student data.
