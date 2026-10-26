# Resilience and administrator alerts

Configure the selected private `.env` (the server uses `.local/.env`):

```dotenv
BOT_ADMIN_IDS=[123456789]
REGISTRAR_MONITOR_CA_FILE=
```

Use your own numeric Telegram ID. Every listed administrator must first open the relevant
bot and press Start. These IDs are notification recipients; they do not bypass registration,
event ownership, or access controls. The example configuration deliberately contains an
empty list so copies cannot send alerts to another deployment's administrator.

## Application behavior

Normal startup migrates the database and checks Telegram. Outlook is checked asynchronously
through its existing single worker, with a 25-second observation timeout, five-minute healthy
interval, and one-minute retry interval. A timeout leaves the existing read attached; another
probe is never queued behind it. An Outlook outage does not disable saved profiles or event
operations. Microsoft can revoke authentication; an alert cannot renew revoked consent.
Stop this bot before interactive `cli.py --login`, then restart it to load the new cache.
`python main.py --check` remains a strict, non-polling diagnostic.

The bot atomically publishes `.bot-health.json` beside its selected environment file every
five seconds and when state changes. The private file contains only timestamps, component
status, and safe exception diagnostics, never student information, codes, prompts, raw exceptions,
tokens, or database connection strings. Outlook errors distinguish HTTP status (for example,
`GraphError: HTTP 503`) from fixed network categories such as `ReadTimeout`, `SSLError`, and
`ConnectionError`. Microsoft sign-in network failures are identified separately and do not
incorrectly request an interactive login. Remote error messages, codes, headers, URLs, and
response bodies are never copied into operational diagnostics.
Verification lookup/submission logs use the same metadata; accepted, failed, and
unconfirmed email outcomes retain their existing behavior and retry policy.

Outlook failure transitions and recovery are logged without raw exception details. The
heartbeat also retains up to 16 Outlook outage records for the current process, including
the first/last failed check, latest safe reason, failed-check count, and recovery time.
Recovery no longer erases these records. Restarting the process starts a new in-memory
history; existing project log retention still applies. Repeated identical failures do not
emit another log line; notification thresholds below are independent of log verbosity.
Database probes have a five-second timeout. Cleanup
failures retry after at most 30 seconds instead of aborting startup; expired answers remain
filtered on reads. HTTP `/health` remains liveness; `/ready` requires database and Telegram
polling and deliberately excludes Outlook availability.

Verification emails have distinct accepted, failed, and unconfirmed statuses in the database,
chat, and logs. `/start` resumes the actual stored status. Only HTTP 202 marks submission
accepted; it does not establish delivery. Ambiguous sends are never automatically repeated.
A code from an ambiguous submission remains valid if it arrives. A definite failure invalidates
its code. Safe log messages identify the outcome without recipient addresses or OTPs.

## Independent supervisor

The stdlib-only `monitoring/` package runs outside the bot. A systemd timer invokes one check
ten seconds after the previous run finishes; an exclusive lock prevents overlaps. It does
not poll Telegram or access Graph. Telegram delivery has a six-second timeout, persistent
retry/backoff, a bounded queue, and at most three submissions per invocation. A network
ambiguity can cause a duplicate alert, but never a duplicate verification email.

Only confirmed, actionable failures interrupt administrators. Isolated `ERROR` log lines,
chat/HTTP/QR/email exceptions, and a single automatic restart remain diagnostics, not pages.
Checks still observe them without sending failure/recovery pairs.

| Condition | Required observed failure duration |
| --- | --- |
| Bot/PostgreSQL/Caddy unavailable, database unavailable, liveness/public HTTPS failure, stalled heartbeat/polling | 30 seconds |
| Outlook unavailable, broadcast/cleanup worker unavailable, monitoring probes failing | 3 minutes |
| Missing/failed backup, disk space under 2 GiB, HTTPS certificate expiry under 48 hours | 5 minutes |

Related availability symptoms share one incident, so a stopped bot does not produce separate
HTTP, polling, and heartbeat messages. While service availability is failing, downstream
Outlook/worker notifications and recoveries are suspended. Dependency status cannot be
inferred from an unavailable service. The heartbeat becomes stale after 45 seconds and polling
after 120 seconds; confirmation starts when the supervisor first observes the failed condition.
Outlook's first probe can occur up to five minutes after the underlying failure, followed by
one-minute retries. These are observation thresholds, not guarantees of end-to-end detection time.

Each incident sends one alert with its observed reason and confirmation duration, without
periodic reminders. Recovery requires 60 seconds of observed healthy state and goes only to
administrators who successfully received the corresponding alert. Brief recoveries do not
close an incident or trigger another alert. An unsent alert is discarded when its outage ends;
a restored Telegram connection cannot replay obsolete failure/recovery pairs. Delivery retries
remain bounded. Removed recipients are excluded from alerts and recoveries.

Confirmation/delivery state survives supervisor invocations. A gap of over two minutes between
checks resets confirmation timers; an incomplete probe cannot establish dependency failure or
recovery. The notification-policy upgrade discards old queued spam without resetting container
metadata or the persisted automatic-restart budget. Raw logs never enter notifications.
Older production images without a heartbeat still use Docker/HTTP availability; in-process
Outlook/polling probes require an application release.

Docker and the existing local service restart crashed processes. If an otherwise running bot
fails liveness/heartbeat checks three times, the supervisor may restart **only that bot**,
at most three times an hour with at least five minutes between attempts. Restart attempts are
persisted before submission. A database or Outlook failure alone never triggers restarts.
An intentionally stopped service/container is reported and left stopped. Database transactions
and persisted registration/form stages survive restarts; accepted in-flight work is drained
before clients close. A forced stop can interrupt an uncommitted operation; it cannot promise
exactly-once processing of a Telegram update already acknowledged by the framework.

### Local development

Use the existing polling service `wiut-social-registrar.service`. For mkcert, set the selected
private env's `REGISTRAR_MONITOR_CA_FILE` to `$(mkcert -CAROOT)/rootCA.pem`'s **expanded absolute
path**, not the literal shell expression. Then install the monitor from the project:

```bash
python deploy/install_watchdog.py --mode dev --root "$PWD" --env-file "$PWD/.env" \
  --url https://127.0.0.1:8443/health
systemctl --user status wiut-social-registrar-watchdog.timer
```

Omit `--url` when the Mini App is disabled; the runtime heartbeat is still checked.
The installer starts only the monitor timer and never starts a second bot process.
User services require the user's service manager to remain running. These instructions do
not change global login/linger settings or other projects.

### Production

Copy the reviewed `monitoring/` package and `deploy/install_watchdog.py` under this project's
`/opt/wiut-social-registrar/operations/`, preserving their relative layout (`operations/monitoring/`
and `operations/deploy/install_watchdog.py`). As root:

```bash
python3 /opt/wiut-social-registrar/operations/deploy/install_watchdog.py \
  --mode production --root /opt/wiut-social-registrar \
  --env-file /opt/wiut-social-registrar/.local/.env \
  --url http://127.0.0.1:18080/health --public-url https://YOUR_PUBLIC_IP/health
systemctl status wiut-social-registrar-watchdog.timer
```

The installer restricts production paths and Compose project name. The root-owned service
has a read-only filesystem except this project's private state directory, no new privileges,
private temporary files, and a three-minute execution limit. It loads configuration from
the selected EnvironmentFile at every invocation. The optional `REGISTRAR_TELEGRAM_API_IPV4`
pins only the notifier's TCP destination; certificate verification and SNI still use
`api.telegram.org`. No global DNS changes or other container restarts occur. Image releases
do not update this host package: reinstall the reviewed monitor separately when it changes.

A second monitor on a different machine can check the public endpoint through the dev bot,
without copying production credentials or enabling repair:

```bash
python deploy/install_watchdog.py --mode external --root "$PWD" --env-file "$PWD/.env" \
  --url https://YOUR_PUBLIC_IP/health --public-url https://YOUR_PUBLIC_IP/health
```

This external monitor runs only while that machine and its user service manager are up.
A fully independent always-on monitor is needed to cover simultaneous host/PC outages.
Telegram cannot deliver alerts during a Telegram outage; queued alerts retry once it returns.
Typical detection is seconds to one check interval plus probe time, not a delivery-time SLA.

An explicitly requested setup alert can be sent outside the test suite by invoking
`python -m monitoring.watchdog --env-dir /path/to/private --test-alert` **with the selected env
loaded privately into that process**. Do not source/print arbitrary dotenv content or paste
tokens into shell arguments. The supervisor never sends test alerts automatically on install.

Official references: [systemd timers](https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html),
[Telegram sendMessage](https://core.telegram.org/bots/api#sendmessage),
[Microsoft sendMail and HTTP 202](https://learn.microsoft.com/en-us/graph/api/user-sendmail),
[Google SRE monitoring](https://sre.google/sre-book/monitoring-distributed-systems/),
[Prometheus alert grouping and inhibition](https://prometheus.io/docs/alerting/latest/alertmanager/),
and [Microsoft refresh token revocation](https://learn.microsoft.com/en-us/entra/identity-platform/refresh-tokens).
